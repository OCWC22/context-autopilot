"""Local subagents: back every internal task kind with the on-device model + RLM.

The router's `local_fn` dispatches here. Each handler does real work locally —
routing/classification, file search (RLM over the repo), summarization (RLM over
long content), code checks (the six-check review), planning, tool-call selection,
and state updates — and returns a LocalResult with a confidence the router uses
to decide whether to accept locally or escalate. The frontier model is touched
only for `hard_reasoning` / `synthesis` (handled by the orchestrator's cloud_fn).

Backends: "mlx" (local mlx_lm.server, $0) or "stub" (deterministic, offline).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from ..checks.rlm_runtime import RLMInspector, load_context, make_sub_lm
from .escalation import LocalResult, Subtask
from .tasks import SubtaskKind


class LocalModel:
    """Minimal local-completion primitive. MLX via OpenAI endpoint, or a stub."""

    def __init__(self, backend: str = "stub", model: str | None = None,
                 base_url: str = "http://127.0.0.1:8080/v1") -> None:
        self.backend = backend
        self.model = model or "local"
        self.base_url = base_url.rstrip("/")

    def complete(self, system: str, user: str, max_tokens: int = 256) -> tuple[str, int, int]:
        tin = (len(system) + len(user)) // 4
        if self.backend == "stub":
            return (f"[local:{self.model}] {user[:80]}", tin, 40)
        import urllib.request

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return text, int(usage.get("prompt_tokens", tin)), int(usage.get("completion_tokens", 60))


class LocalSubagents:
    """Callable bundle used as the router's `local_fn`. Dispatches by SubtaskKind
    to a local-model/RLM-backed handler. Holds a repo root for context-bound
    tasks and an RLM sub-LM (the same local model) for file search / summarize."""

    def __init__(self, model: LocalModel, repo: str | Path = ".",
                 rlm_chunk_chars: int = 6000, rlm_max_subcalls: int = 16,
                 memory_backend=None, state_backend=None) -> None:
        self.model = model
        self.repo = Path(repo)
        self.memory = memory_backend   # EverMind/EverOS ("Revermind") or local
        self.state = state_backend     # Butterbase or local
        sub_lm = make_sub_lm(model.backend, model=model.model, base_url=model.base_url)
        self.rlm = RLMInspector(sub_lm, chunk_chars=rlm_chunk_chars, max_subcalls=rlm_max_subcalls)

    def __call__(self, task: Subtask) -> LocalResult:
        handler: Callable[[Subtask], LocalResult] = {
            SubtaskKind.search.value: self._file_search,
            SubtaskKind.file_inspect.value: self._file_search,
            SubtaskKind.summarize.value: self._summarize,
            SubtaskKind.classify.value: self._classify,
            SubtaskKind.tool_use.value: self._tool_call,
            SubtaskKind.plan.value: self._plan,
            SubtaskKind.memory_lookup.value: self._memory_lookup,
            SubtaskKind.state_update.value: self._state_update,
            SubtaskKind.code_review.value: self._code_check,
            SubtaskKind.security_review.value: self._code_check,
            SubtaskKind.ci_check.value: self._code_check,
            SubtaskKind.test_run.value: self._code_check,
            SubtaskKind.dependency_scan.value: self._code_check,
            SubtaskKind.deploy_validate.value: self._code_check,
        }.get(task.kind, self._generic)
        return handler(task)

    # --- context-heavy handlers use RLM (context held OUTSIDE the model) ---

    def _file_search(self, task: Subtask) -> LocalResult:
        paths = [self.repo / r for r in task.context_refs] if task.context_refs else [self.repo]
        ctx = load_context(paths)
        terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", task.prompt)[:6]
        res = self.rlm.inspect(task.prompt, ctx, prefilter=terms or None)
        found = bool(res.slices)
        return LocalResult(
            text=res.answer,
            confidence=0.9 if found else 0.45,
            tokens_in=res.context_chars // 4,
            tokens_out=len(res.answer) // 4,
        )

    def _summarize(self, task: Subtask) -> LocalResult:
        paths = [self.repo / r for r in task.context_refs] if task.context_refs else []
        ctx = load_context(paths) if paths else []
        if ctx:
            res = self.rlm.inspect("Summarize the key points relevant to: " + task.prompt, ctx)
            return LocalResult(res.answer, 0.8, res.context_chars // 4, len(res.answer) // 4)
        text, tin, tout = self.model.complete("Summarize concisely.", task.prompt)
        return LocalResult(text, 0.75, tin, tout)

    def _code_check(self, task: Subtask) -> LocalResult:
        from ..checks.orchestrator import run_review

        checks = (task.kind,) if task.kind in (
            "security_review", "ci_check", "test_run", "dependency_scan",
        ) else None
        # map our SubtaskKind names to check names where they differ
        name_map = {"security_review": "security", "ci_check": "cicd",
                    "test_run": "test_execution", "dependency_scan": "dependency_analysis",
                    "deploy_validate": "deployment_validation", "code_review": "code_quality"}
        sel = (name_map.get(task.kind),) if name_map.get(task.kind) else None
        report = run_review(self.repo, checks=sel, sub_lm_backend=self.model.backend)
        gate = report["gate"]["gate"]
        ev_chars = report["gate"]["total_evidence_chars"]
        ctx_chars = report["gate"]["total_context_chars"]
        return LocalResult(
            text=json.dumps({"gate": gate, "checks": report["gate"]["checks"]}),
            confidence=0.9,
            tokens_in=ctx_chars // 4,
            tokens_out=ev_chars // 4,
        )

    # --- light handlers use the local model directly ---

    def _classify(self, task: Subtask) -> LocalResult:
        text, tin, tout = self.model.complete(
            "Classify the request into one short label. Reply with only the label.",
            task.prompt,
            max_tokens=16,
        )
        return LocalResult(text.strip(), 0.85, tin, tout)

    def _tool_call(self, task: Subtask) -> LocalResult:
        text, tin, tout = self.model.complete(
            "Choose the single tool and arguments to accomplish this. Reply as JSON {tool, args}.",
            task.prompt,
            max_tokens=128,
        )
        return LocalResult(text.strip(), 0.8, tin, tout)

    def _plan(self, task: Subtask) -> LocalResult:
        text, tin, tout = self.model.complete(
            "Draft a short numbered plan (3-7 steps) of concrete subtasks.",
            task.prompt,
            max_tokens=256,
        )
        # Complex/ambiguous goals get lower confidence -> router may escalate.
        complex_signal = len(task.prompt) > 400 or any(
            w in task.prompt.lower() for w in ("architecture", "redesign", "migrate", "tradeoff", "ambiguous")
        )
        return LocalResult(text.strip(), 0.6 if complex_signal else 0.8, tin, tout)

    def _memory_lookup(self, task: Subtask) -> LocalResult:
        # Long-context recall via EverMind/EverOS (or local). Returns compact
        # episode summaries + profile — a cheap retrieval, not a frontier call.
        if self.memory is not None:
            hits = self.memory.search(task.prompt) or ""
            return LocalResult(hits or "no relevant memory", 0.9 if hits else 0.6, len(task.prompt) // 4, len(hits) // 4)
        return self._summarize(task)

    def _state_update(self, task: Subtask) -> LocalResult:
        # Deterministic state write to the agent DB (Butterbase or local).
        if self.state is not None:
            self.state.put(f"note:{abs(hash(task.prompt)) % 10_000_000}", task.prompt[:500])
        return LocalResult(text=f"state: {task.prompt[:80]}", confidence=1.0, tokens_in=0, tokens_out=0)

    def _generic(self, task: Subtask) -> LocalResult:
        text, tin, tout = self.model.complete("Answer concisely.", task.prompt)
        return LocalResult(text, 0.7, tin, tout)
