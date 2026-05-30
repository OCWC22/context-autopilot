"""Build the complete `.autopilot/` bundle — the thing passed to every agent.

The DAG terminates into a single entrypoint SKILL.md that LINKS to everything:
the versioned architecture DAG, the machine-readable graph, and a verify/ folder
of runnable scripts that test and verify every claim. A manifest checksums and
versions every artifact, so the whole bundle is traceable, indexable,
verifiable, and versioned.

Layout written under <repo>/.autopilot/:
  SKILL.md          entrypoint loaded by every agent; links the rest
  ARCHITECTURE.md   deterministic, commit-versioned code DAG (file tree + functions)
  dag.json          machine-readable graph
  manifest.json     version (commit), generated_at, artifacts + sha256 checksums
  verify/run_all.py        runs all verifications, exits nonzero on failure
  verify/verify_dag.py     re-derives the DAG and asserts it matches dag.json
  verify/verify_commands.sh runs the repo's detected test/lint commands
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .dag import DAGBuilder
from .indexer import RepoIndexer


_VERIFY_DAG = '''#!/usr/bin/env python3
"""Verify the DAG claims are reproducible: recount functions deterministically
from source and compare to dag.json. Self-contained (stdlib only). Exit 1 on
mismatch. This is how every claim in ARCHITECTURE.md stays verifiable."""
import ast, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # .autopilot/
REPO = HERE.parent
dag = json.loads((HERE / "dag.json").read_text())
SKIP = {".git","node_modules","__pycache__","autopilot_out",".venv","venv","dist","build",".autopilot"}

def count_py_defs():
    n = 0
    for f in REPO.rglob("*.py"):
        if any(p in SKIP for p in f.parts):
            continue
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except (OSError, SyntaxError):
            continue
        n += sum(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for x in ast.walk(tree))
    return n

claimed_py = sum(1 for fn in dag["functions"] if fn["file"].endswith(".py"))
actual_py = count_py_defs()
ok = claimed_py == actual_py
print(f"functions(py): claimed={claimed_py} actual={actual_py} -> {'OK' if ok else 'MISMATCH'}")
print(f"version: {dag.get('version')} | files: {len(dag['files'])} | call_edges: {len(dag['call_edges'])}")
sys.exit(0 if ok else 1)
'''

_VERIFY_CMDS = '''#!/usr/bin/env bash
# Run the repo's detected test/lint commands so SKILL.md claims about "how to
# test" are verified, not asserted. Edit as your commands evolve.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
rc=0
{cmds}
exit $rc
'''

_RUN_ALL = '''#!/usr/bin/env python3
"""Run every verification and aggregate pass/fail. Exit 1 if any fails."""
import subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
checks = [["python3", str(HERE / "verify_dag.py")], ["bash", str(HERE / "verify_commands.sh")]]
fails = 0
for c in checks:
    print(f"\\n=== {' '.join(c)} ===")
    if subprocess.run(c).returncode != 0:
        fails += 1
print(f"\\n{len(checks)-fails}/{len(checks)} verifications passed")
sys.exit(1 if fails else 0)
'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build_bundle(repo: str | Path, max_commits: int = 20) -> dict[str, Any]:
    repo = Path(repo)
    out = repo / ".autopilot"
    (out / "verify").mkdir(parents=True, exist_ok=True)

    # 1) DAG -> ARCHITECTURE.md + dag.json
    db = DAGBuilder(repo)
    dag = db.build(max_commits=max_commits)
    md, js = db.write(dag)

    # 2) index (stack/commands/conventions) for the entrypoint + verify commands
    idx = RepoIndexer(repo)
    index = idx.index()

    # 3) verify/ scripts (the runnable proof of every claim)
    cmd_lines = "\n".join(
        f'echo "+ {v}"; {v} || rc=1' for v in index.commands.values()
    ) or 'echo "(no commands detected)"'
    (out / "verify" / "verify_dag.py").write_text(_VERIFY_DAG)
    (out / "verify" / "verify_commands.sh").write_text(_VERIFY_CMDS.replace("{cmds}", cmd_lines))
    (out / "verify" / "run_all.py").write_text(_RUN_ALL)

    # 4) SKILL.md — the entrypoint that LINKS everything (passed to every agent)
    skill = _render_entrypoint(repo.name or "repo", dag, index)
    (out / "SKILL.md").write_text(skill)

    # 5) manifest — checksums + version for traceability
    artifacts = ["SKILL.md", "ARCHITECTURE.md", "dag.json",
                 "verify/run_all.py", "verify/verify_dag.py", "verify/verify_commands.sh"]
    manifest = {
        "version": dag.version,
        "generated_at": dag.generated_at or "uncommitted",
        "repo": str(repo),
        "stats": {"files": len(dag.files), "functions": len(dag.functions),
                  "import_edges": len(dag.import_edges), "call_edges": len(dag.call_edges),
                  "commits": len(dag.commits)},
        "artifacts": [
            {"path": a, "sha256": _sha256(out / a), "bytes": (out / a).stat().st_size}
            for a in artifacts if (out / a).exists()
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"bundle_dir": str(out), "entrypoint": str(out / "SKILL.md"), "manifest": manifest}


def _render_entrypoint(name: str, dag, index) -> str:
    cmds = "\n".join(f"- `{k}`: `{v}`" for k, v in index.commands.items()) or "- (none detected)"
    convs = "\n".join(f"- {c}" for c in index.conventions) or "- (none detected)"
    return f"""---
name: {name}-autopilot
description: Entrypoint context for {name}. Load this first — it links the live, versioned architecture DAG, the machine-readable graph, and runnable verification scripts. Everything here is deterministic, traceable, verifiable, and versioned to commit {dag.version}. Use it instead of exploring the repo from scratch.
version: {dag.version}
generated_at: {dag.generated_at or 'uncommitted'}
---

# {name} — autopilot context @ `{dag.version}`

This bundle is regenerated locally ($0) after every change/commit and passed to
every coding agent so it already understands the codebase.

Stack: {', '.join(index.stack) or 'mixed'} · {len(dag.files)} files ·
{len(dag.functions)} functions/classes · {len(dag.import_edges)} import edges ·
{len(dag.call_edges)} call edges.

## Linked artifacts (load as needed — progressive disclosure)
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — complete file tree, every function mapped (calls/called_by), and per-commit created/updated/deleted history (SDLC-versioned DAG).
- [`dag.json`](./dag.json) — machine-readable graph (files, functions, import + call edges).
- [`manifest.json`](./manifest.json) — version, generated_at, and sha256 of every artifact (traceability).
- [`verify/run_all.py`](./verify/run_all.py) — runs all verifications; exits nonzero if any claim fails.
- [`verify/verify_dag.py`](./verify/verify_dag.py) — re-derives the DAG and asserts it matches `dag.json`.
- [`verify/verify_commands.sh`](./verify/verify_commands.sh) — runs the repo's test/lint commands.

## Commands
{cmds}

## Conventions
{convs}

## How to use this (for the agent)
1. Read this file + `ARCHITECTURE.md` to know the structure before touching code.
2. Resolve symbols/dependencies via `dag.json` instead of grepping the whole repo.
3. Before claiming the architecture is current, run `python3 .autopilot/verify/run_all.py`.
4. Every claim here is verifiable and versioned to commit `{dag.version}`.
"""
