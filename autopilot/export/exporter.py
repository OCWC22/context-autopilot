"""Orchestrate export: read Claude Code + Codex local logs, build memory, and
write the raw dataset that the dataset builders consume.

Outputs (under <out>/dataset/):
  traces.jsonl     all reconstructed coding traces
  accepted.jsonl   traces with an inferred-accepted patch
  rejected.jsonl   traces whose edits look interrupted / un-applied
  memory.json      the derived MemoryProfile
  summary.json     counts + provenance
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import Config, DEFAULT
from ..types import CodingTrace, MemoryProfile
from . import claude_code, codex
from .conventions import build_memory


@dataclass
class ExportResult:
    traces: list[CodingTrace]
    memory: MemoryProfile
    accepted: list[CodingTrace]
    rejected: list[CodingTrace]
    summary: dict

    def write(self, out_dir: Path) -> None:
        ds = out_dir
        ds.mkdir(parents=True, exist_ok=True)
        _write_jsonl(ds / "traces.jsonl", (t.to_dict() for t in self.traces))
        _write_jsonl(ds / "accepted.jsonl", (t.to_dict() for t in self.accepted))
        _write_jsonl(ds / "rejected.jsonl", (t.to_dict() for t in self.rejected))
        (ds / "memory.json").write_text(json.dumps(self.memory.to_dict(), indent=2))
        (ds / "summary.json").write_text(json.dumps(self.summary, indent=2))


def _write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def export(
    cfg: Config = DEFAULT,
    sources: tuple[str, ...] = ("claude_code", "codex"),
    limit: int | None = None,
) -> ExportResult:
    traces: list[CodingTrace] = []
    provenance: dict[str, int] = {}

    if "claude_code" in sources:
        cc = claude_code.load_traces(cfg.paths.claude_home, limit=limit)
        provenance["claude_code"] = len(cc)
        traces.extend(cc)
    if "codex" in sources:
        cx = codex.load_traces(cfg.paths.codex_home, limit=limit)
        provenance["codex"] = len(cx)
        traces.extend(cx)

    accepted = [t for t in traces if t.patch_accepted and t.edits]
    rejected = [t for t in traces if t.edits and not t.patch_accepted]
    memory = build_memory(traces)

    summary = {
        "traces_imported": len(traces),
        "accepted_diffs": len(accepted),
        "rejected_patches": len(rejected),
        "with_test_signal": sum(1 for t in traces if t.tests_passed is not None),
        "provenance": provenance,
        "task_type_counts": _counts(t.task_type for t in traces),
        "risk_counts": _counts(t.risk_level for t in traces),
        "note": "patch_accepted is INFERRED (no labeled accept/reject field).",
    }
    return ExportResult(traces, memory, accepted, rejected, summary)


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out
