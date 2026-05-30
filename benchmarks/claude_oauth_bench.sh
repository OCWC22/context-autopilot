#!/usr/bin/env bash
# Real head-to-head: Claude Code (OAuth, explores the repo) vs local-first
# (answers from the prebuilt .autopilot index). Run AFTER `claude /login`.
#
#   bash benchmarks/claude_oauth_bench.sh [repo_dir]
#
# Emits BENCHMARK.results.json and prints a table. Requires the `claude` CLI
# logged in (OAuth) and `autopilot` importable (pip install -e . or PYTHONPATH).
set -uo pipefail
REPO="${1:-.}"
MODEL="${BENCH_MODEL:-sonnet}"
Q='In this Python repo, what function decides whether a coding subtask runs on the LOCAL model vs escalates to the FRONTIER model, and which file defines it? Answer in ONE sentence: file path + function name.'

cd "$REPO" || exit 1
echo "# building local index (\$0)…"
T0=$(python3 -c 'import time;print(time.time())')
python3 -m autopilot.cli index --repo . >/dev/null 2>&1
T1=$(python3 -c 'import time;print(time.time())')
INDEX_MS=$(python3 -c "print(round(($T1-$T0)*1000))")
ARCH=$(cat .autopilot/ARCHITECTURE.md 2>/dev/null | head -c 6000)

run() {  # $1=label  $2=prompt
  /usr/bin/env claude -p "$2" --output-format json --permission-mode bypassPermissions --model "$MODEL" 2>/dev/null
}

echo "# CONFIG A: Claude Code, no index (explores repo)…"
A=$(run A "$Q")
echo "# CONFIG B: local-first (answers from prebuilt index, no file reads)…"
B=$(run B "$Q

Use ONLY this architecture context; do NOT read or search files:
$ARCH")

python3 - "$A" "$B" "$INDEX_MS" <<'PY'
import json, sys
a, b, index_ms = sys.argv[1], sys.argv[2], float(sys.argv[3])
def parse(s):
    try: d=json.loads(s)
    except Exception: return {}
    u=d.get("usage",{})
    return {"cost":d.get("total_cost_usd"),"ms":d.get("duration_ms"),"turns":d.get("num_turns"),
            "in":u.get("input_tokens"),"out":u.get("output_tokens"),
            "cache_read":u.get("cache_read_input_tokens"),"result":(d.get("result") or "")[:160]}
A,B=parse(a),parse(b)
out={"index_ms":index_ms,"claude_code_no_index":A,"local_first_indexed":B}
json.dump(out, open("BENCHMARK.results.json","w"), indent=2)
def tot(x): return (x.get("in") or 0)+(x.get("out") or 0)+(x.get("cache_read") or 0)
print(f"\n{'config':26}{'tokens':>10}{'cost$':>10}{'ms':>9}{'turns':>7}")
print(f"{'Claude Code (no index)':26}{tot(A):>10}{str(A.get('cost')):>10}{str(A.get('ms')):>9}{str(A.get('turns')):>7}")
print(f"{'local-first (indexed)':26}{tot(B):>10}{str(B.get('cost')):>10}{str(B.get('ms')):>9}{str(B.get('turns')):>7}")
if tot(A) and tot(B):
    print(f"\ntokens saved: {round(100*(tot(A)-tot(B))/tot(A),1)}%  (local index built in {index_ms:.0f} ms, $0)")
print("\nA answer:", A.get("result")); print("B answer:", B.get("result"))
PY
