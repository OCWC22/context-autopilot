#!/usr/bin/env bash
# Live demo — runs the real product end to end. ~90s.
#   bash demo/run_demo.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
b() { printf "\n\033[1;36m== %s ==\033[0m\n" "$1"; }

b "1) \$0 local index -> commit-versioned DAG + SKILL.md bundle"
python3 -m autopilot.cli index --repo . | python3 -c "import sys,json;d=json.load(sys.stdin);m=d['manifest'];print(f\"  version {m['version']}  files {m['stats']['files']}  functions {m['stats']['functions']}  call_edges {m['stats']['call_edges']}\")"

b "2) Verify every claim is reproducible"
python3 .autopilot/verify/verify_dag.py | head -1

b "3) Eval — local-first (indexed) vs normal Claude Code"
python3 -m autopilot.cli eval | grep -E "TOKENS|TIME|COST|FRONTIER|ACCURACY"

b "4) Submit — Butterbase (backend) + EverMind (memory, LIVE)"
python3 -m autopilot.cli submit | python3 -c "import sys,json;d=json.load(sys.stdin);r=d.get('results',{});print('  EverMind:',r.get('evermind'));print('  Butterbase:',r.get('butterbase'));print('  submission_code:',d.get('submission_code'))"

b "done — github.com/OCWC22/personal-coding-autopilot"
