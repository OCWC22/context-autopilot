# Personal Coding Model Autopilot

Turn your own Claude Code / Codex history into a personal coding model that takes
low-risk repo work off metered API spend, with a Claude / Codex fallback for the
hard tasks. Target model: **Qwen3-Coder-Next**.

The pipeline is one loop: export your local agent traces, build a memory profile
plus SFT and verifiable-reward RL tasks, warm-start a student with LoRA SFT,
sharpen it with GRPO against checks that actually run (tests, typecheck, lint),
serve it serverless on Modal/vLLM with LoRA hot-swap, and route to it only when
a conservative policy says it is safe — verifying before accept.

## The honest version

Read [`RECEIPTS.md`](./RECEIPTS.md) before pitching this. Every load-bearing
claim is Exa-validated there with a `supported` / `partially_supported` /
`overclaim` verdict. The short form:

- **Savings are against METERED API spend, not a flat plan.** An always-on
  A100 is ~$1,800/mo — more than the $20 / $100 / $200 subscription it would
  replace. The lever is the **June 15 2026** Anthropic billing split, which
  pushes Agent-SDK / `claude -p` / third-party-harness usage onto a separate
  monthly credit metered at full API rates. That metered category is exactly
  what this automation lives in. (RECEIPTS cluster 1, 7.)
- **A few hundred diffs buys style/convention adaptation, not new capability.**
  ~382 diffs sits in the fragile 300–500 band: workable for narrow convention
  adaptation with strong regularization and a held-out eval gate, prone to
  memorization, and it does **not** make the model smarter. (RECEIPTS cluster 5.)
- **Serve serverless, scale-to-zero.** `ServeConfig.min_containers = 0`; you pay
  $0 while idle. Always-on dedicated only wins above ~40% utilization, which a
  solo developer never hits. (RECEIPTS cluster 3, 7.)
- **Keep the router conservative.** Code generation is the worst routing case
  (~22% safely routed in the literature). The router falls back to Claude/Codex
  on any typecheck/lint failure and verifies personal output before shipping it.
  (RECEIPTS cluster 7.)
- **Reward stays binary on tests.** Pass-rate is a miscalibrated surrogate in
  critic-free RL, so the tests reward is pass/fail, not graded. (RECEIPTS
  cluster 6.)

## Architecture

```
  ~/.claude/projects/*.jsonl              autopilot export
  ~/.codex/sessions/<Y>/<M>/<D>/*    ─────────────────────────┐
  (plaintext agent transcripts)                               │
                                                              ▼
                                            ┌─────────────────────────────────┐
                                            │  dataset/ + memory profile       │
                                            │  sft_{train,eval}.jsonl (chat)   │
                                            │  rl_{train,eval}.jsonl (RLTask)  │
                                            │  MemoryProfile (prefs/conventions)│
                                            └─────────────────────────────────┘
                                                              │
                          Stage A: LoRA SFT warm-up           ▼
                          (student, single GPU)   ┌───────────────────────────┐
                          strong regularization,  │  train/sft_lora.py        │
                          held-out eval gate       │  r=8, dropout 0.1, ≤2 ep │
                                                   └───────────────────────────┘
                                                              │
                          Stage B: GRPO with               ▼
                          VERIFIABLE rewards       ┌───────────────────────────┐
                          run_checks() applies a   │  train/grpo.py            │
                          unified diff in a temp    │  rewards/{reward_funcs,   │
                          repo, runs tests/type/    │           sandbox}.py     │
                          lint -> binary tests       │  verifiers + prime-rl     │
                          reward + shaping          └───────────────────────────┘
                                                              │
                          Modal serverless GPU,            ▼
                          vLLM OpenAI-compatible   ┌───────────────────────────┐
                          endpoint, LoRA hot-swap  │  serve/modal_app.py       │
                          scale-to-zero            │  --enable-lora, A100-80GB │
                                                   │  min_containers = 0       │
                                                   └───────────────────────────┘
                                                              │
                          route: personal vs               ▼
                          Claude/Codex fallback    ┌───────────────────────────┐
                          conservative policy,     │  serve/router.py          │
                          VERIFY BEFORE ACCEPT     │  fall back on type/lint   │
                                                   │  failure; verify output   │
                                                   └───────────────────────────┘
```

## Quickstart

The offline core needs no GPU and no heavy installs — it is standard-library
only.

```bash
pip install -e .

autopilot export    # read local Claude Code / Codex logs -> dataset
autopilot build     # dataset -> SFT examples + RL tasks + eval split + memory
autopilot route     # dry-run the conservative routing policy over built tasks
autopilot plan      # print the model / serve / economics plan
```

Then the GPU stages, each gated behind its own extras so the core stays light:

```bash
# Stage A: LoRA SFT warm-up on the student (single consumer GPU)
pip install -e '.[train]'
autopilot train-sft

# Stage B: verifiable-reward GRPO via verifiers + prime-rl
pip install -e '.[rl]'
autopilot train-rl

# Serve: Modal serverless GPU + vLLM, scale-to-zero, LoRA hot-swap
pip install -e '.[serve]'
modal deploy autopilot/serve/modal_app.py
```

No GPU run was performed in this build. The train/serve modules are written to
run when their extras are installed and a GPU is present; see
"What's real vs scaffolded" below.

## Models

| Role | Model | Where it runs | Notes |
|---|---|---|---|
| `student` | `Qwen/Qwen2.5-Coder-7B-Instruct` | Single GPU | Runnable now; the default for Stage A / Stage B end-to-end on one card. |
| `target` | `Qwen/Qwen3-Coder-Next` (80B-A3B) | 4× 80GB bf16 (or quantized single-node) | Scale run. Open-weight Apache-2.0, 80B total / 3B active MoE, built for coding agents, 70.6 SWE-Bench Verified. (RECEIPTS cluster 5.) |
| `target_small` | `Qwen/Qwen3-Coder-30B-A3B-Instruct` | Single 80GB | Middle rung: 30.5B/3.3B, 128 experts, when 4×80GB isn't available. |

The 80B target is **not single-GPU**: it needs 4×80GB bf16 or a quantized
single-node config. LoRA on a MoE coder is the weakest link — validate the
adapter actually loads on the MoE base before claiming it. (RECEIPTS cluster 4.)

## Reward design

GRPO optimizes against checks that run. Weights are `DEFAULT.reward`
(`RewardWeights`); `compute_reward()` in `rewards/reward_funcs.py` is pure and
stdlib-only.

| Component | Weight | Signal |
|---|---|---|
| `tests_pass` | **+1.0** | **Binary** pass/fail — the correctness oracle. |
| `typecheck_pass` | +0.5 | Type checker clean. |
| `lint_pass` | +0.3 | Linter clean. |
| `minimal_diff` | +0.2 | Diff close to the reference patch size. |
| `follows_memory` | +0.2 | Respects the `MemoryProfile` conventions. |
| `build_breaks` | -1.0 | Patch fails to build / compile. |
| `edits_unrelated_files` | -0.5 | Touches files outside scope. |
| `adds_unwanted_dependency` | -0.5 | Introduces an unwanted dependency. |
| `violates_preference` | -0.5 | Violates a stated coding preference. |

The tests component is intentionally **binary**, not graded by pass-rate:
pass-rate is a miscalibrated surrogate in critic-free RL, and reward quality is
bounded by test coverage — weak or flaky tests silently reward wrong code.
(RECEIPTS cluster 6.)

## Layout

```
personal-coding-autopilot/
├── README.md                  # this file
├── RECEIPTS.md                # Exa-backed validation of every load-bearing claim
├── pyproject.toml             # core has zero deps; [train]/[rl]/[serve] extras
├── skill/
│   ├── SKILL.md               # Claude Code Skill front matter
│   └── export_traces.py       # bundled scraper: the script that does the real work
├── autopilot/
│   ├── config.py              # DEFAULT Config: models, train, serve, reward, paths
│   ├── types.py               # RLTask, EvalCheck, MemoryProfile, SFTExample, ...
│   ├── cli.py                 # `autopilot` entrypoint; lazy-imports GPU stages
│   ├── export/                # Claude Code + Codex log readers -> traces
│   │   ├── claude_code.py     #   (accept/reject is inferred heuristically)
│   │   ├── codex.py
│   │   ├── classify.py
│   │   ├── conventions.py     #   -> MemoryProfile
│   │   └── exporter.py
│   ├── dataset/               # traces -> SFT chat examples + RL tasks + split
│   │   ├── build_sft.py
│   │   ├── build_tasks.py
│   │   └── split.py
│   ├── rewards/               # PURE, stdlib-only
│   │   ├── reward_funcs.py    #   compute_reward / reward_to_scalar
│   │   └── sandbox.py         #   run_checks: apply diff in temp repo, run checks
│   ├── serve/
│   │   ├── router.py          # personal vs Claude/Codex; verify before accept
│   │   └── modal_app.py       # Modal serverless vLLM endpoint (extras: serve)
│   └── train/
│       ├── sft_lora.py        # Stage A (extras: train)
│       └── grpo.py            # Stage B (extras: rl)
└── tests/                     # fixtures + offline-core tests
```

## What's real vs scaffolded

- **Offline core — runnable and tested now.** `export`, `dataset`, `rewards`,
  `sandbox`, `router`, and `cli` are standard-library only. `pip install -e .`
  then `autopilot export / build / route / plan` runs anywhere with no GPU and
  no heavy installs. These are covered by the tests in `tests/`.
- **Train / serve modules — runnable when extras + a GPU are present.**
  `train/sft_lora.py`, `train/grpo.py`, and `serve/modal_app.py` import their
  heavy deps lazily and are written to run once `[train]` / `[rl]` / `[serve]`
  are installed on a GPU box. The CLI imports them inside `try/except
  ImportError`, so a plain `import autopilot.cli` never pulls torch/vLLM/Modal.
- **No GPU run was performed in this build.** The GPU stages compile cleanly and
  follow the documented APIs; they have not been executed end-to-end here. Where
  a claim depends on that, it is marked `partially_supported` in `RECEIPTS.md`.

## Local-first variant: offline GLM-5.1 distillation + multi-subagent RLM review

A second path keeps the bulk of inference **local and cheap**: distill GLM-5.1
into a small MLX student that runs on a **16GB MacBook**, and run engineering
review as **six RLM-driven subagents** whose sub-LM is that local model. Claude
is the parent orchestrator only. (Receipts: `RECEIPTS.md` v2.)

```
GLM-5.1 (cloud teacher, Z.ai API, $0.95/$3.15 MTok)   <- too big for a Mac (754B MoE)
        |  black-box sequence-level KD (gold patch + reasoning)
        v
MLX QLoRA student  (Qwen2.5-Coder-3B/7B-4bit, offline, ~20 min on 16GB)   <- separate offline process
        |  mlx_lm.fuse
        v
mlx_lm.server  (local OpenAI endpoint, $0)  ---------------+
                                                           | = RLM sub-LM (the bulk)
6 subagents -- each RLM(depth=1) externalizes its context -+
  cicd . security . code_quality . test_execution . dependency_analysis . deployment_validation
        |  compact evidence only (findings + path:line refs, not raw blobs)
        v
parent orchestrator (Claude) -- deployment gate (pass / warn / fail)
```

```bash
# offline distillation (separate process; --run executes on a Mac, else prints the MLX commands)
export ZAI_API_KEY=...                        # Z.ai key for the GLM-5.1 teacher
autopilot distill --max-tasks 200             # GLM-5.1 -> MLX QLoRA data + commands
pip install mlx-lm && autopilot distill --run # actually QLoRA on the 16GB Mac
autopilot mlx-serve                           # serve the distilled student locally (OpenAI @ :8080)

# multi-subagent engineering review (RLM context externalization)
autopilot review /path/to/repo --sub-lm stub  # offline, no model needed
autopilot review /path/to/repo --sub-lm mlx   # uses the local MLX server as the RLM sub-LM
```

The agentic version is `workflows/engineering_review.py` (run via the Workflow
tool): six subagents inspect in parallel, each using the `mcp__rlm__*` MCP at
**depth=1** (depth>=2 overthinks — RECEIPTS v2), returning compact evidence to a
parent gate. `autopilot review` is the library/CLI equivalent, verified offline.

**Why RLM here:** CI logs, lockfiles, scan output, and traces are huge. RLM holds
them *outside* the model as data and sub-queries only the relevant slices, so the
parent's context — and your frontier-token bill — stays tiny regardless of input
size. The `compression_ratio` in the review report is context-externalized ÷
evidence-returned.

## Generalizes beyond coding: the local-first agent stack (Hermes / OpenClaw / personal agents)

The engineering review is one instance of a general primitive. One user request
fans into dozens of hidden subagent calls — plan, search, memory lookup, tool
use, the six checks, email drafts, calendar actions, retries. If each hits a
frontier model, the subscription quietly becomes a metered-API bill (the June 15
2026 Agent-SDK-credit split makes that literal — RECEIPTS v2). `autopilot/agent/`
is a framework-agnostic router any agent can drop in:

```
user request -> parent agent (frontier, sparing)
             -> local/on-device subagents (cheap, private)   <- most calls land here
             -> private context + memory (RLM-externalized)
             -> cheap verification loop
             -> cloud escalation ONLY on low confidence / failed verify / high stakes
             -> human gate for irreversible actions -> final action
```

```python
from autopilot.agent import EscalationRouter, Subtask, CostLedger, SubtaskKind
router = EscalationRouter(local_fn=mlx_call, verify_fn=cheap_check,
                          cloud_fn=claude_call, human_gate_fn=ask_user,
                          ledger=CostLedger())
outcome = router.route(Subtask(SubtaskKind.search.value, "find the deploy config"))
```

Plug in your own `local_fn` (MLX), `verify_fn`, `cloud_fn` (Claude), and
`human_gate_fn`. The `CostLedger` makes the hidden bill visible: it reports the
local share and what the same work would have cost if every subtask had gone to
the frontier model.

Demonstration over the exact subtask list above (offline stubs): **13 calls → 11
local (84.6%), 2 cloud (`plan` + `hard_reasoning` only), 1 gated
(`calendar_action`, held for human approval), ~56% cost saved** vs an
all-frontier baseline — conservative, since local is $0 regardless of tokens.
Policy is rule-based and auditable (`agent/tasks.py`): routine read-mostly work
runs local; hard reasoning escalates; mutating/irreversible actions
(`email_send`, `calendar_action`, `payment`, `deploy_apply`, `delete`) are gated.

## Status

Built for the **OpenEnv hackathon** by **Touchdown Labs**. Stage B runs on the
PrimeIntellect **verifiers** + **prime-rl** substrate for verifiable-reward GRPO.
The local-first variant adds offline GLM-5.1->MLX distillation and a
multi-subagent RLM engineering-review workflow. This is a research scaffold with
an honest evidence trail, not a turnkey product — read [`RECEIPTS.md`](./RECEIPTS.md)
for exactly what the evidence supports and where a sharp judge will push.
