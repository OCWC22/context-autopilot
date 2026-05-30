"""DAG + bundle tests: deterministic graph, linking entrypoint, verifiable +
versioned artifacts with checksums."""

from __future__ import annotations

import json
import subprocess
import sys

from autopilot.evals import seed_eval_repo
from autopilot.repo import DAGBuilder, build_bundle


def test_dag_is_deterministic_and_complete(tmp_path):
    seed_eval_repo(tmp_path)
    repo = tmp_path / "eval_repo"
    d1 = DAGBuilder(repo).build()
    d2 = DAGBuilder(repo).build()
    assert d1.to_json()["functions"] == d2.to_json()["functions"]   # deterministic
    assert len(d1.files) > 5 and len(d1.functions) > 0
    # calc.py defines add/mul and is connected
    quals = {f.qualname for f in d1.functions}
    assert any(q.endswith("calc.py::add") for q in quals)


def test_bundle_links_everything_and_is_versioned(tmp_path):
    seed_eval_repo(tmp_path)
    repo = tmp_path / "eval_repo"
    res = build_bundle(repo)
    out = repo / ".autopilot"
    for rel in ("SKILL.md", "ARCHITECTURE.md", "dag.json", "manifest.json",
                "verify/run_all.py", "verify/verify_dag.py", "verify/verify_commands.sh"):
        assert (out / rel).exists(), rel
    skill = (out / "SKILL.md").read_text()
    # entrypoint links the DAG + verify scripts
    assert "ARCHITECTURE.md" in skill and "verify/run_all.py" in skill and "dag.json" in skill
    # manifest checksums + version every artifact (traceable + versioned)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["version"] and all(a["sha256"] for a in manifest["artifacts"])


def test_verify_script_confirms_dag_claims(tmp_path):
    seed_eval_repo(tmp_path)
    repo = tmp_path / "eval_repo"
    build_bundle(repo)
    # the verifier re-derives the DAG and asserts it matches dag.json -> exit 0
    r = subprocess.run([sys.executable, str(repo / ".autopilot" / "verify" / "verify_dag.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
