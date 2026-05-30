"""Local-first task orchestrator.

Runs a task as a pipeline of internal subtasks — plan, file search, code checks,
summarize, state update, tool calls — each handled by a LOCAL subagent (model +
RLM). It accumulates only compact, high-value results, persists them to external
state, and escalates to the frontier model EXACTLY ONCE for the final synthesis
(or for any step the policy marks `hard_reasoning`). The frontier model sees the
packed high-value context, never the raw logs/files.

Offline (`backend="stub"`) it runs end-to-end with no model or network, so you
can see the fan-out and the local-vs-frontier split. With `backend="mlx"` the
local subagents hit the on-device server; `frontier_fn` wires the cloud model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import DEFAULT, Config
from .escalation import CloudResult, EscalationRouter, RouteOutcome, Subtask, Tier
from .ledger import CostLedger
from .local import LocalModel, LocalSubagents
from .memory_backend import make_memory_backend, memory_backend_name
from .state_backend import make_state_backend, state_backend_name
from .tasks import DEFAULT_POLICY, SubtaskKind


class ContextPacker:
    """Accumulates compact subtask results and packs only the high-value ones for
    the frontier model — the 'report final result / high-value context' step."""

    def __init__(self, char_budget: int = 2000) -> None:
        self.items: list[tuple[str, str]] = []  # (kind, compact_result)
        self.char_budget = char_budget

    def add(self, kind: str, result: str) -> None:
        self.items.append((kind, (result or "").strip()))

    def pack(self) -> str:
        out, used = [], 0
        # high-value first: gates/verdicts/findings before generic summaries
        prio = {"code_review": 0, "security_review": 0, "ci_check": 0, "test_run": 0,
                "dependency_scan": 0, "deploy_validate": 0, "file_inspect": 1, "summarize": 2}
        for kind, res in sorted(self.items, key=lambda kr: prio.get(kr[0], 3)):
            line = f"[{kind}] {res}"
            if used + len(line) > self.char_budget:
                line = line[: max(0, self.char_budget - used)] + "…"
            out.append(line)
            used += len(line)
            if used >= self.char_budget:
                break
        return "\n".join(out)


def stub_frontier(task: Subtask) -> CloudResult:
    """Offline stand-in for the frontier call. Real deployments pass a frontier_fn
    that sends `task.prompt` (goal + packed high-value context) to Claude/Codex."""
    return CloudResult(
        text="[FRONTIER synthesis] reviewed packed evidence; "
        "issued final judgment over compact context only.",
        model="claude-sonnet-4-6",
        tokens_in=len(task.prompt) // 4,
        tokens_out=180,
    )


@dataclass
class AgentRun:
    goal: str
    result: str
    outcomes: list[dict] = field(default_factory=list)
    ledger: dict = field(default_factory=dict)
    state_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "result": self.result,
            "steps": self.outcomes,
            "ledger": self.ledger,
            "state_path": self.state_path,
        }


def default_pipeline(goal: str, repo: str) -> list[Subtask]:
    """A representative internal-task fan-out for a 'review & report' goal. Every
    step is local except the final synthesis (which escalates)."""
    return [
        Subtask(SubtaskKind.plan.value, f"Plan how to review and report on: {goal}"),
        Subtask(SubtaskKind.memory_lookup.value, f"Recall prior context relevant to: {goal}"),
        Subtask(SubtaskKind.file_inspect.value, "Locate CI configs, manifests, lockfiles, and logs"),
        Subtask(SubtaskKind.ci_check.value, "CI/CD health"),
        Subtask(SubtaskKind.security_review.value, "security issues"),
        Subtask(SubtaskKind.dependency_scan.value, "dependency risks"),
        Subtask(SubtaskKind.test_run.value, "test results"),
        Subtask(SubtaskKind.summarize.value, "Summarize the findings so far"),
        Subtask(SubtaskKind.state_update.value, "Record the gate + findings to memory"),
        Subtask(SubtaskKind.synthesis.value, f"Produce the final report and recommendation for: {goal}"),
    ]


class LocalFirstOrchestrator:
    def __init__(
        self,
        repo: str | Path = ".",
        backend: str = "stub",
        cfg: Config = DEFAULT,
        frontier_fn: Callable[[Subtask], CloudResult] | None = None,
    ) -> None:
        self.repo = Path(repo)
        self.cfg = cfg
        model = LocalModel(backend, model=cfg.mlx.student,
                           base_url=f"http://{cfg.mlx.serve_host}:{cfg.mlx.serve_port}/v1")
        # Sponsor backends: Butterbase (state) + EverMind/"Revermind" (memory),
        # auto-selected by env keys; offline local defaults otherwise.
        self.state_backend = make_state_backend(cfg)
        self.memory_backend = make_memory_backend(cfg)
        self.local = LocalSubagents(model, repo=self.repo,
                                    rlm_chunk_chars=cfg.checks.rlm_chunk_chars,
                                    rlm_max_subcalls=cfg.checks.rlm_max_subcalls,
                                    memory_backend=self.memory_backend,
                                    state_backend=self.state_backend)
        self.ledger = CostLedger()
        self.packer = ContextPacker(char_budget=2 * cfg.checks.evidence_char_budget)
        self.router = EscalationRouter(
            local_fn=self.local,
            cloud_fn=frontier_fn or stub_frontier,
            policy=DEFAULT_POLICY,
            ledger=self.ledger,
        )

    def run(self, goal: str, steps: list[Subtask] | None = None, synthesize: bool = True) -> AgentRun:
        """Run the pipeline. If synthesize=False, run only the LOCAL internal
        steps and return the packed high-value context as the result — for when
        the CALLER is the frontier model (e.g. Hermes) and will synthesize."""
        steps = steps or default_pipeline(goal, str(self.repo))
        if not synthesize:
            steps = [s for s in steps if s.kind != SubtaskKind.synthesis.value]
        state = _next_state_dir(self.cfg)
        run_id = state.name
        events = []
        outcomes: list[dict] = []
        final = ""

        for st in steps:
            # the synthesis step carries the packed high-value context to the frontier
            if st.kind == SubtaskKind.synthesis.value:
                st = Subtask(st.kind, f"{st.prompt}\n\nHigh-value context:\n{self.packer.pack()}",
                             stakes=st.stakes)
            outcome: RouteOutcome = self.router.route(st)
            self.packer.add(st.kind, outcome.result)
            rec = {
                "kind": st.kind,
                "tier": outcome.tier,
                "escalated": outcome.escalated,
                "confidence": round(outcome.confidence, 2),
                "result_preview": (outcome.result or "")[:100],
            }
            outcomes.append(rec)
            events.append(rec)
            self.state_backend.log_event(run_id, rec)  # -> Butterbase or local
            if st.kind == SubtaskKind.synthesis.value:
                final = outcome.result

        if not synthesize:
            # hand the packed high-value context to the caller (the frontier model)
            final = self.packer.pack()

        payload = {"goal": goal, "result": final, "ledger": self.ledger.summary()}
        self.state_backend.save_run(run_id, payload)  # -> Butterbase or local
        # persist this run to long-context memory (EverMind/"Revermind" or local)
        self.memory_backend.add([
            {"role": "user", "content": goal},
            {"role": "assistant", "content": (final or self.packer.pack())[:2000]},
        ])
        self.memory_backend.flush()

        (state / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        (state / "result.json").write_text(json.dumps(payload, indent=2))

        return AgentRun(
            goal=goal,
            result=final or "(no synthesis step)",
            outcomes=outcomes,
            ledger=self.ledger.summary(),
            state_path=str(state),
        )

    def pretty(self, run: AgentRun) -> str:
        local = sum(1 for o in run.outcomes if o["tier"] == Tier.local.value)
        cloud = sum(1 for o in run.outcomes if o["tier"] == Tier.cloud.value)
        lines = [
            f"Local-first run — {len(run.outcomes)} subtasks: {local} local, {cloud} frontier",
            f"  state: {state_backend_name(self.state_backend)} | memory: {memory_backend_name(self.memory_backend)}",
            f"  cost ${run.ledger['actual_cost_usd']} vs all-frontier ${run.ledger['all_frontier_baseline_usd']} "
            f"({run.ledger['saved_pct']}% saved) | local share {run.ledger['local_share_pct']}%",
            "",
        ]
        for o in run.outcomes:
            tier = o["tier"].upper()
            mark = " ->FRONTIER" if o["tier"] == Tier.cloud.value else ""
            lines.append(f"  [{tier:6}] {o['kind']:18} conf={o['confidence']}{mark}")
        lines += ["", f"  final (frontier): {run.result[:120]}"]
        return "\n".join(lines)


def _next_state_dir(cfg: Config) -> Path:
    base = Path(cfg.paths.out) / "agent_runs"
    base.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit()]
    run_dir = base / str((max(existing) + 1) if existing else 1)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


if __name__ == "__main__":  # pragma: no cover
    import sys

    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    orch = LocalFirstOrchestrator(repo=repo, backend="stub")
    run = orch.run(f"review {repo} before deploy")
    print(orch.pretty(run))
