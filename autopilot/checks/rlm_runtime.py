"""RLM-style context externalization for the engineering-check subagents.

Implements the Recursive Language Model pattern (arXiv 2512.24601) at depth=1:
the long context (logs/configs/traces) is held OUTSIDE the model as data; the
check peeks, regex-prefilters, chunks, and maps a sub-LM over only the relevant
slices, then stitches compact evidence. Depth is hard-capped at 1 and sub-calls
at `max_subcalls` because depth>=2 overthinks and latency explodes
(reproduction study arXiv 2603.02615 — RECEIPTS.md v2).

The sub-LM is a plain callable `(query, context_slice) -> str`. In production it
is the local MLX model (`mlx_serve.client`); for offline tests pass a stub.
Two backends:
  - this self-contained RLM-lite (stdlib only, always available), and
  - delegation to the `mcp__rlm__*` MCP when running inside an agent that has it
    (see `rlm_mcp_plan` for the exact tool sequence).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# A sub-LM: given a query and a slice of externalized context, return a compact
# answer (a few lines). May return "" / "none" when the slice is irrelevant.
SubLM = Callable[[str, str], str]


@dataclass
class ContextItem:
    ref: str          # locator the parent can re-open, e.g. "ci/build.log"
    text: str         # the (possibly huge) content, held as data, never sent whole


@dataclass
class RLMResult:
    answer: str                       # stitched compact evidence
    slices: list[tuple[str, str]] = field(default_factory=list)  # (ref, sub-answer)
    subcalls: int = 0
    context_chars: int = 0
    evidence_chars: int = 0
    truncated: bool = False           # hit max_subcalls stopping cap


def load_context(paths: Iterable[str | Path], max_bytes_each: int = 2_000_000) -> list[ContextItem]:
    """Read files/dirs into ContextItems. Directories are walked shallowly.
    Binary / oversized files are skipped (logs and configs are text)."""
    items: list[ContextItem] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    items.extend(_read_one(f, max_bytes_each))
        elif path.is_file():
            items.extend(_read_one(path, max_bytes_each))
    return items


def _read_one(f: Path, max_bytes: int) -> list[ContextItem]:
    try:
        if f.stat().st_size > max_bytes:
            data = f.read_bytes()[:max_bytes].decode("utf-8", "ignore")
        else:
            data = f.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        return []
    if not data.strip():
        return []
    return [ContextItem(ref=str(f), text=data)]


class RLMInspector:
    """Depth-1 RLM inspector. Externalizes context, prefilters, and maps a
    sub-LM over relevant slices with a hard stopping cap."""

    def __init__(
        self,
        sub_lm: SubLM,
        chunk_chars: int = 6000,
        max_subcalls: int = 24,
        depth: int = 1,
    ) -> None:
        if depth != 1:
            # Enforced, not configurable: depth>=2 degrades (RECEIPTS v2).
            depth = 1
        self.sub_lm = sub_lm
        self.chunk_chars = chunk_chars
        self.max_subcalls = max_subcalls

    def inspect(
        self,
        query: str,
        context: list[ContextItem],
        prefilter: list[str] | None = None,
        peek_chars: int = 1500,
    ) -> RLMResult:
        total_chars = sum(len(c.text) for c in context)
        result = RLMResult(answer="", context_chars=total_chars)

        # 1) PEEK + GREP: select relevant items/regions without sending everything.
        relevant = self._prefilter(context, prefilter, peek_chars)

        # 2) CHUNK + MAP: sub-LM over each relevant slice (the bulk work, on MLX).
        sub_answers: list[tuple[str, str]] = []
        for ref, slice_text in relevant:
            if result.subcalls >= self.max_subcalls:
                result.truncated = True
                break
            ans = (self.sub_lm(query, f"[{ref}]\n{slice_text}") or "").strip()
            result.subcalls += 1
            if ans and ans.lower() not in ("none", "n/a", "no issues", "nothing"):
                sub_answers.append((ref, ans))

        # 3) STITCH: combine the compact sub-answers (still depth-1; the parent
        #    check does the final reduce/verdict — no deeper recursion here).
        result.slices = sub_answers
        result.answer = self._stitch(sub_answers)
        result.evidence_chars = len(result.answer)
        return result

    def _prefilter(
        self,
        context: list[ContextItem],
        prefilter: list[str] | None,
        peek_chars: int,
    ) -> list[tuple[str, str]]:
        patterns = [re.compile(p, re.I) for p in (prefilter or [])]
        out: list[tuple[str, str]] = []
        for item in context:
            if patterns:
                # keep only regions around matches (grep-then-window), bounded
                windows = self._match_windows(item.text, patterns)
                for w in windows:
                    out.append((item.ref, w))
            else:
                # no prefilter: chunk the whole item (peek the head if enormous)
                text = item.text
                if len(text) > self.chunk_chars * 8:
                    text = text[: peek_chars] + "\n...\n" + text[-self.chunk_chars:]
                for chunk in self._chunk(text):
                    out.append((item.ref, chunk))
        return out

    def _match_windows(self, text: str, patterns: list[re.Pattern[str]]) -> list[str]:
        lines = text.splitlines()
        keep: set[int] = set()
        for i, line in enumerate(lines):
            if any(p.search(line) for p in patterns):
                for j in range(max(0, i - 3), min(len(lines), i + 4)):
                    keep.add(j)
        if not keep:
            return []
        # group contiguous kept lines into windows, capped at chunk size
        windows: list[str] = []
        cur: list[str] = []
        for i in sorted(keep):
            cur.append(lines[i])
            if sum(len(x) for x in cur) >= self.chunk_chars:
                windows.append("\n".join(cur))
                cur = []
        if cur:
            windows.append("\n".join(cur))
        return windows

    def _chunk(self, text: str) -> list[str]:
        return [text[i : i + self.chunk_chars] for i in range(0, len(text), self.chunk_chars)]

    def _stitch(self, sub_answers: list[tuple[str, str]]) -> str:
        if not sub_answers:
            return "no issues found"
        return "\n".join(f"- ({ref}) {ans}" for ref, ans in sub_answers)


def make_sub_lm(backend: str = "mlx", model: str | None = None, **kw) -> SubLM:
    """Build a sub-LM callable. 'mlx' -> local mlx_lm.server (cheap, $0).
    'stub' -> deterministic offline stub for tests."""
    if backend == "stub":
        return _stub_sub_lm()
    if backend == "mlx":
        from ..mlx_serve.client import mlx_sub_lm

        return mlx_sub_lm(model=model, **kw)
    raise ValueError(f"unknown sub_lm backend: {backend}")


def _stub_sub_lm() -> SubLM:
    """Offline stub: flags lines containing obvious problem keywords. Lets the
    whole check pipeline run + be tested without a model."""
    bad = re.compile(
        r"\b(error|fail(ed|ure)?|exception|traceback|denied|vulnerab|critical|"
        r"cve-|secret|password|api[_-]?key|deprecat|timed out|exit code [1-9])\b",
        re.I,
    )
    def stub(query: str, context_slice: str) -> str:
        hits = [ln.strip() for ln in context_slice.splitlines() if bad.search(ln)]
        if not hits:
            return "none"
        return "; ".join(hits[:3])[:200]
    return stub


def rlm_mcp_plan() -> list[str]:
    """The tool sequence a subagent uses to run this on the `mcp__rlm__*` MCP
    instead of the in-process RLM-lite (preferred when available). Documented so
    the workflow agents follow it verbatim."""
    return [
        "ToolSearch select:mcp__rlm__rlm_init,mcp__rlm__rlm_add_buffer,mcp__rlm__rlm_grep,mcp__rlm__rlm_peek,mcp__rlm__rlm_chunk_indices,mcp__rlm__rlm_sub_query,mcp__rlm__rlm_sub_query_result",
        "rlm_init(session_id='check-<name>')",
        "rlm_add_buffer(<files/logs/configs/traces paths or globs>)",
        "rlm_grep(<check-specific patterns>)  # narrow before any sub-call",
        "rlm_peek(<top matches>)              # confirm structure",
        "rlm_sub_query(<query>, <chunk indices>)  # sub-LM = local MLX; depth=1 only",
        "rlm_sub_query_result(...)            # collect compact answers, stitch, return CheckEvidence",
    ]
