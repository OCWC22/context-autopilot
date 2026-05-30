"""Parent orchestrator for the multi-subagent engineering review.

Fans out the six checks concurrently (each externalizes its own long context via
RLM and returns compact evidence), then computes a deterministic deployment
gate. In the agentic version this orchestrator IS Claude (the parent), and each
check is a subagent whose RLM sub-LM is the local MLX model — see
workflows/engineering_review.py. This module is the standalone/library path and
runs offline with a stub sub-LM.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..config import DEFAULT, Config
from .evidence import CheckEvidence, gate_from_evidence
from .rlm_runtime import make_sub_lm
from .registry import build_checks


def run_review(
    repo: str | Path,
    cfg: Config = DEFAULT,
    checks: tuple[str, ...] | None = None,
    sub_lm_backend: str | None = None,
) -> dict[str, Any]:
    repo = Path(repo)
    names = checks or cfg.checks.checks
    backend = sub_lm_backend or cfg.checks.sub_lm
    sub_lm = make_sub_lm(
        backend,
        model=cfg.mlx.student,
        base_url=f"http://{cfg.mlx.serve_host}:{cfg.mlx.serve_port}/v1",
    )
    instances = build_checks(
        names,
        sub_lm=sub_lm,
        chunk_chars=cfg.checks.rlm_chunk_chars,
        max_subcalls=cfg.checks.rlm_max_subcalls,
    )

    evidences: list[CheckEvidence] = []
    with ThreadPoolExecutor(max_workers=len(instances) or 1) as pool:
        futures = {
            pool.submit(c.run, repo, cfg.checks.evidence_char_budget): c.name for c in instances
        }
        for fut in futures:
            try:
                evidences.append(fut.result())
            except Exception as e:  # a failing check shouldn't sink the review
                evidences.append(
                    CheckEvidence(
                        check=futures[fut],
                        verdict="unknown",
                        confidence="low",
                        summary=f"check raised: {e}",
                        notes=["exception during run"],
                    )
                )

    gate = gate_from_evidence(evidences)
    return {
        "repo": str(repo),
        "sub_lm": backend,
        "gate": gate,
        "evidence": [e.to_dict() for e in evidences],
    }


def pretty(report: dict[str, Any]) -> str:
    g = report["gate"]
    lines = [
        f"Engineering review — gate: {g['gate'].upper()}  (sub-LM: {report['sub_lm']})",
        f"  findings: {g['total_findings']}  |  context seen: {g['total_context_chars']:,} chars "
        f"-> evidence: {g['total_evidence_chars']:,} chars  |  sub-calls: {g['total_subcalls']}",
        "",
    ]
    for e in report["evidence"]:
        lines.append(
            f"  [{e['verdict'].upper():5}] {e['check']:22} "
            f"top={e['top_severity']:8} findings={len(e['findings'])} "
            f"compression={e['compression_ratio']}x"
        )
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    import sys

    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    rep = run_review(repo, sub_lm_backend="stub")
    print(pretty(rep))
    print(json.dumps(rep["gate"], indent=2))
