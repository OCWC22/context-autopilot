# Benchmark — local-first vs normal Claude Code

Machine: macOS-26.3-arm64-arm-64bit-Mach-O · Python 3.14.4

## A. Harness benchmark (real, measured — runs offline now)

Two configs over seeded ContextBench-style tasks (gold context files + a real failing test).
"Claude Code (full ctx)" = send the whole repo to the frontier model (worst case);
"local-first (indexed)" = selective retrieval + compression, escalate only when needed.

| metric | Claude Code (full ctx) | local-first (indexed) | delta |
|---|--:|--:|--:|
| tokens in | 23,894 | 299 | **-98.7%** |
| est. time (ms) | 491,404.8 | 9,760.5 | **-98.0%** |
| cost (USD) | $0.080682 | $0.004932 | **-93.9%** |
| frontier calls | 2 | 1 | **-1 avoided** |
| retrieval F1 | 0.18 | 0.5 | **+0.32** |
| tests passed | 1/1 | 1/1 | success preserved: True |

Real: token counts, retrieval recall/precision vs gold, test pass/fail, local wall-clock.
Estimated: frontier inference time (600ms TTFT + 50 tok/s) — no live frontier call.
Reproduce: `autopilot eval --json`.

## B. Real Claude Code OAuth benchmark (run on-site)

The headless `claude` CLI here was not logged in ("Please run /login"), so the live
OAuth head-to-head is gated on an interactive login. After `claude /login`:

```bash
bash benchmarks/claude_oauth_bench.sh .
```

It runs the SAME codebase question two ways — Claude Code exploring the repo (no index)
vs answering from the prebuilt `.autopilot` index (no file reads) — and reports tokens,
cost, duration, and turns from `claude --output-format json`. Local index builds in
~300 ms at $0.

## C. Sponsor integration (live calls need on-site keys)

- **Butterbase** (state/backend + judging): `autopilot submit` provisions tables and
  writes project/eval/artifact rows via the Data API. Needs BUTTERBASE_APP_ID + bb_sk key
  (promo BUILD0530). Submission code: build0530.
- **EverMind/EverOS** (agent memory): durable repo decisions + architecture + eval results
  via /memories/agent. Needs EVEROS_API_KEY.
- Both auto-select when keyed; offline local backends otherwise. `autopilot submit` runs
  dry-run without keys.

## D. Real public-repo benchmark — psf/requests (measured)

Cloned `github.com/psf/requests` and ran `autopilot index` + `autopilot repo-context`:

- Index (real DAG): **62 files · 801 functions · 128 import edges · 3,166 call edges**, $0, on-device.
- Whole repo ≈ **147,794 tokens**.
- Query "which file & function handle redirect resolution and retries in a Session" →
  retrieved `src/requests/sessions.py` (correct), `models.py`, `cookies.py`; the relevant
  files are 236,551 chars (~59,137 tok) but compress to **4,101 chars (~1,025 tokens) — 57.7×**.
- So the agent gets the **right ~1,025 tokens instead of ~147,794** to reload the repo: **−99.3%**.

Reproduce: `git clone --depth 1 https://github.com/psf/requests /tmp/requests && autopilot index --repo /tmp/requests && autopilot repo-context "which file and function handle redirects and retries in a Session" --repo /tmp/requests`
