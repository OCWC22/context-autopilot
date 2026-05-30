# RECEIPTS — Personal Coding Model Autopilot

Exa-backed validation of every load-bearing claim, run 2026-05-30. Verdicts:
`supported` / `partially_supported` / `overclaim`. Read this before pitching —
it tells you what the evidence actually supports and where a sharp judge will
push.

## TL;DR (the one thing that changes the pitch)

**Self-hosting a personal model does NOT beat a flat $20 / $100 / $200 Claude
subscription.** An always-on A100 is ~$1,800/mo — more than the plan it would
replace. The savings are real **only against metered / pay-as-you-go API
spend** — which is exactly what Anthropic's **June 15 2026** billing split
pushes agentic/Agent-SDK/third-party-harness usage onto. So:

- Frame savings against **metered API spend**, not the flat subscription.
- Serve **serverless, scale-to-zero** (the only solo-volume-viable config).
- A few hundred diffs buys **style/convention adaptation, not new capability** —
  pair the personal model with retrieved memory + a held-out eval gate, and keep
  a conservative router (code generation is the *worst* routing case, ~22%).

---

## Cluster 1 — Claude plan tiers ($20/$100/$200) — **supported (high)**

Confirmed on Anthropic's own pricing page: Pro $20/mo ($17 annual), Max 5x
$100/mo, Max 20x $200/mo; Claude Code included on all three. Usage is shared
across chat + Claude Code.

**The nuance that powers the whole product:** as of **June 15 2026**, Anthropic
splits billing — interactive terminal Claude Code stays bundled, but
programmatic / Agent SDK / `claude -p` / GitHub Actions / third-party-harness
(ACP) usage draws from a separate monthly credit ($20/$100/$200) **metered at
full API rates**. Subscriptions historically subsidized agentic usage ~15–30×
vs API.

- [claude.com/pricing](https://claude.com/pricing) — "$20 if billed monthly … Includes Claude Code"
- [Help Center: Claude Code with Pro/Max](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan) — "usage limits … shared across Claude and Claude Code"
- [Zed blog](https://zed.dev/blog/anthropic-subscription-changes) — "splitting … billing into two pools … $20/$100/$200 Agent SDK credit … billed at full API rates"
- [Simon Willison, Apr 22 2026](https://simonwillison.net/2026/Apr/22/claude-code-confusion/)
- API rates: Opus 4.8 $5/$25, Sonnet 4.6 $3/$15, Haiku 4.5 $1/$5 per MTok

**Risk:** Touchdown's automation *is* the metered category — so the lever is
the metered credit, not the cheap interactive bundle. Don't claim a fixed
"heavy bill" number (the $150–250/dev/mo figures are third-party, not primary).

## Cluster 2 — Paste-in skill exports traces/diffs/conventions — **partially_supported (high)**

Mechanism is real. Claude Code Skills are official (a `SKILL.md` + bundled
scripts Claude runs via bash with full filesystem access). Claude Code writes
**complete plaintext JSONL transcripts** under `~/.claude/projects/…` — every
prompt, tool call, and `Edit` `oldString`/`newString`/`structuredPatch`. Codex
stores rollout JSONL under `~/.codex/sessions/<Y>/<M>/<D>/`.

- [Claude Code Skills docs](https://code.claude.com/docs/en/skills)
- [.claude directory docs](https://code.claude.com/docs/en/claude-directory) — "Full conversation transcript … plaintext"
- [Sessions docs](https://code.claude.com/docs/en/sessions) — "Transcripts are stored as JSONL"
- [Reverse-engineered edit schema](https://ai4curation.io/ai-blame/explanation/claude-traces/) — `oldString, newString, structuredPatch`
- [Codex CLI features](https://developers.openai.com/codex/cli/features)

**Two honest caveats (baked into the code):** (1) a `SKILL.md` reads nothing by
itself — the real work is a **bundled scraper script** (`skill/export_traces.py`);
(2) **accept/reject is not a labeled field** — the format is undocumented and
rejections are *inferred* heuristically (see `export/claude_code.py`). Default
30-day transcript retention means data may not exist for light users.

## Cluster 3 — Modal CLI provisions GPU + vLLM endpoint — **partially_supported (high)**

Modal officially supports OpenAI-compatible vLLM serving: attach a GPU via a
Python decorator (`gpu="H100:1"`), deploy with **one CLI command**
(`modal deploy`), get a live HTTPS endpoint. Per-second pricing is real.

- [Modal vLLM example](https://modal.com/docs/examples/vllm_inference)
- [Modal pricing](https://modal.com/pricing) — A100-80GB **$0.000694/s (~$2.50/hr)**, H100 **$0.001097/s (~$3.95/hr)**; $30/mo free credit; **$0 while idle**
- [Cold start docs](https://modal.com/docs/guide/cold-start) — tune Volume caching / FAST_BOOT / scaledown

**Caveat:** "turnkey" is true only because **we ship & maintain the Modal file**
(`serve/modal_app.py`) — Modal isn't one-flag-magic. Cold starts are
seconds-to-minutes without weight caching; keeping warm = paying for idle.

## Cluster 4 — vLLM serves the personal model + LoRA hot-swap — **supported (high)**

vLLM exposes an OpenAI-compatible API, serves LoRA via `--enable-lora`
(addressable by name in the `model` field), supports multi-LoRA batching
(`max_loras`) and **runtime hot-swap** (`/v1/load_lora_adapter`) — so per-user
personal models are routable like any model name.

- [vLLM OpenAI server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)
- [vLLM LoRA](https://docs.vllm.ai/en/stable/features/lora.html) — `--enable-lora`, dynamic load/unload
- [Qwen3-Coder-30B-A3B card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) — 30.5B/3.3B, 128 experts
- [vLLM Qwen3-Next recipe](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3-Next.md) — **80B-A3B needs 4× H200/A100 (bf16)** or FP8 tp=4

**Caveat:** the 80B target is **not single-GPU** (4×80GB bf16, or ~48–80GB
quantized single-node). **LoRA on a MoE coder is the weakest link** — validate
the adapter actually loads on the MoE base before claiming it.

## Cluster 5 — Personal model = LoRA/SFT a Qwen coder; is ~382 diffs enough? — **partially_supported (high)**

Qwen3-Coder-Next is real: open-weight **Apache-2.0**, 80B total / 3B active MoE,
built for coding agents, **70.6 SWE-Bench Verified**, released Feb 2026.
LoRA/SFT on accepted diffs is a standard 2026 technique.

- [Qwen3-Coder-Next card](https://huggingface.co/Qwen/Qwen3-Coder-Next) — "80B total / 3B activated … designed for coding agents"
- [arXiv 2603.00729](https://arxiv.org/abs/2603.00729) — trained via "synthesis of verifiable coding tasks … reinforcement learning … from environment feedback"
- Data-size floors: [Particula](https://particula.tech/blog/how-much-data-fine-tune-llm) (50–100 floor, 500–2000 for generation), [Effloow 2026](https://effloow.com/articles/llm-fine-tuning-lora-qlora-guide-2026) (500–1000 = style/format adaptation)

**Caveat:** ~hundreds of diffs sits in the **fragile 300–500 band** — workable
for narrow convention/style adaptation **with strong regularization + held-out
eval**, prone to memorization, unlikely to add capability. Don't claim it makes
the model "smarter." (Code default `TrainConfig`: r=8, dropout 0.1, ≤2 epochs.)

## Cluster 6 — "Accepted diffs are supervision, tests are rewards" — **supported (high)**

Both halves are established, peer-reviewed technique, not marketing.

- [SWE-bench (ICLR 2024)](https://openreview.net/pdf?id=VTF8yNQM66) — fail-to-pass tests as the correctness oracle; fine-tuned SWE-Llama on 19k gold patches
- [RLEF, arXiv 2410.02089](https://arxiv.org/pdf/2410.02089) — binary held-out-test reward
- CodeRL reward: **+1.0 pass / −0.3 fail / −0.6 runtime err / −1.0 no compile**
- [SWE-RL](https://github.com/opendilab/awesome-RLVR) — rule-based reward, 41.0 SWE-bench Verified
- GRPO + RLVR is the standard recipe ([AWS GRPO/RLVR](https://aws.amazon.com/blogs/machine-learning/overcoming-reward-signal-challenges-verifiable-rewards-based-reinforcement-learning-with-grpo-on-sagemaker-ai/))
- Pass-rate vs binary nuance: [arXiv 2605.02944](https://arxiv.org/html/2605.02944v1) — pass-rate is a miscalibrated surrogate in critic-free RL → we keep tests **binary**

**Caveat:** reward quality is bounded by **test coverage** — weak/flaky tests
silently reward wrong code. And the precedent operates at scale (19k PRs / 10.7M
commits); a solo repo yields far fewer clean fail-to-pass instances.

## Cluster 7 — Routing cuts spend; solo GPU math nets positive — **partially_supported (high)**

Two halves, opposite verdicts:

1. **Routing/cascading to cheaper models = strongly supported** cost lever:
   31–85% reported savings with quality largely preserved on routine traffic.
   - [RouteNLP](https://arxiv.org/html/2604.23577) — 58% cost cut, 91% acceptance (8-wk pilot)
   - [UCCI](https://arxiv.org/html/2605.18796) — 31% cut at micro-F1 0.91 on H100
   - [Kaman.ai](https://dev.kaman.ai/papers/intelligent-llm-routing.pdf) — 35–55%, **but code gen only 22%** (classifiers keep coding on frontier models)

2. **Solo self-hosted GPU economics = do NOT net positive vs a flat plan.**
   - [KickLLM break-even](https://kickllm.com/research/open-source-vs-api.html) — "Below $2000/mo in API costs: use APIs. Self-hosting overhead erases savings."
   - [Prem AI](https://blog.premai.io/serverless-llm-deployment-runpod-vs-modal-vs-lambda-2026/) — Modal A100-80GB ~$2.50/hr; dedicated beats serverless only above ~40% utilization
   - Always-on A100 ≈ **$1,800/mo** ≫ the $20–200 plan it would replace

**Conclusion baked into the design:** route against **metered** spend, serve
**scale-to-zero**, keep the router conservative, and verify personal output
before shipping it. This is why `serve/router.py` falls back on any
typecheck/lint failure and `ServeConfig.min_containers = 0`.

---

# RECEIPTS v2 — MLX / GLM-5.1 / RLM extension (offline Mac distillation + multi-subagent review)

## v2-A — GLM-5.1 as the distillation teacher — **supported (high)**

GLM-5.1 ([zai-org/GLM-5.1](https://huggingface.co/zai-org/GLM-5.1), arXiv
2602.15763) is a **754B-param MoE / 40B active**, **MIT-licensed**, open-weight
agentic-coding model. **SWE-Bench Pro 58.4 (#1, beats GPT-5.4 / Claude Opus
4.6)**; 200K context; trained on Huawei Ascend. Z.ai API is OpenAI-compatible
with a `thinking` mode at **$0.95 / $3.15 per MTok** ([docs.z.ai](https://docs.z.ai/guides/llm/glm-5.1)).

**Decision:** it needs **256GB+ even quantized / 1.65TB disk** — so it **cannot
run on a Mac**. We use it as a **teacher via API (black-box)**. That forces
**black-box, sequence-level KD** (teacher generates gold patch + reasoning →
student SFT), *not* white-box logit / on-policy OPD, which needs the teacher's
weights co-hosted ([On-Policy Distillation survey, arXiv 2604.00626](https://arxiv.org/html/2604.00626v1);
[KDFlow, arXiv 2603.01875](https://www.arxiv.org/pdf/2603.01875)). The cheap API
makes generating a few hundred teacher targets cost cents. (`autopilot/distill/`)

## v2-B — MLX student on a 16GB Mac — **supported (high)**

[mlx-lm](https://github.com/ml-explore/mlx-lm) does on-device **QLoRA fine-tune**
(`mlx_lm.lora --train`, auto-QLoRA on a 4-bit base) + `mlx_lm.fuse` +
OpenAI-compatible `mlx_lm.server`. RAM reality
([Markaicode 2026](https://markaicode.com/run-fine-tune-llms-mac-mlx-lm/), [DEV](https://dev.to/brunocerberus/running-local-llms-on-apple-silicon-2ecm)):

| RAM | Runnable | Not |
|---|---|---|
| **16GB** | 7B-4bit (~4.5GB) / 8B-4bit / 3B comfortably; QLoRA 7B ~20-25 min | 30B-A3B (~33GB), Coder-Next-4bit (~50GB) |

**Decision:** student = **`mlx-community/Qwen2.5-Coder-3B-Instruct-4bit`** (safe
on 16GB) with a 7B-4bit option; memory knobs `--num-layers 8 --batch-size 1
--grad-checkpoint`. Caveat: coding models need the correct `tool_parser_type`
(`qwen3_coder`) in `tokenizer_config.json`. (`autopilot/mlx_serve/`, `MLXConfig`)

## v2-C — RLM for context externalization — **supported, with a hard depth cap (high)**

[Recursive Language Models, arXiv 2512.24601](https://arxiv.org/abs/2512.24601)
([code](https://github.com/alexzhang13/rlm)): hold the long prompt as a REPL
variable; the model peeks/greps/chunks and **recursively sub-calls** an LM over
slices. Beats long-context scaffolds by a median 13-130% at comparable cost; the
no-sub-call REPL ablation alone already scales past the context limit.

**Critical caveat (the reproduction study, [arXiv 2603.02615](https://arxiv.org/html/2603.02615)):**
depth=1 helps on complex long-context (DeepSeek v3.2 0%→42% on OOLONG), but
**depth=2 degrades and explodes latency (3.6s→344s)**, and RLM *hurts* on simple
retrieval. **Decision:** `ChecksConfig.rlm_depth = 1` (hard-enforced in
`RLMInspector`), `rlm_max_subcalls` stopping cap, only applied to genuinely long
context. The `mcp__rlm__*` MCP is the preferred runtime; the **sub-LM is the
local MLX model** so the bulk reading is ~$0 and Claude stays the parent only.

## v2-D — distillation technique — **supported (high)**

Sequence-level KD (teacher completions → student SFT) is the DeepSeek-R1-distill
recipe and is well-established ([OPD survey](https://arxiv.org/html/2604.00626v1)).
On-policy distillation (OPD/GKD/MiniLLM) is stronger but needs white-box teacher
logits; [Lightning-OPD](https://github.com/jet-ai-projects/Lightning-OPD) even
precomputes them offline — **but all of that requires teacher weights we don't
have for a 754B API model**. So the Mac path is **black-box sequence-level KD**;
the white-box GRPO/OPD path stays in the cloud (`autopilot/train/`, the existing
verifiers + prime-rl substrate). Honest: a few hundred distilled examples
transfers GLM-5.1's *style/conventions*, not its full capability.

**Net architecture:** GLM-5.1 (cloud teacher, API) → black-box KD → MLX QLoRA
student (16GB Mac, offline, separate process) → `mlx_lm.server` (local, $0) →
RLM-depth-1 engineering checks use it as the sub-LM → Claude orchestrates the
gate. Frontier tokens spent only on orchestration; the bulk runs local.
