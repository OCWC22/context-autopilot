# Citations — the local repo-context layer + eval harness

The thesis: **this is an inference-orchestration problem, not a code-model
problem.** The waste is repeatedly paying frontier-model prices for repo
discovery, context retrieval, summarization, and state reconstruction. A small
local code model + skills + memory + selective retrieval does that cheap
repeated work; the frontier model is called only when stronger reasoning is
needed. The product is the **eval harness** that proves it.

No single paper states our exact product sentence; it's a combination. Each
component below maps to where it lives in this repo.

| # | Paper | Claim we use | Where in this repo |
|---|---|---|---|
| 1 | **Repoformer** — Wu et al., ICML 2024 ([PMLR v235](https://proceedings.mlr.press/v235/wu24a.html)) | Learn *when* retrieval is needed; always-retrieve is wasteful/harmful. Up to ~70% inference speedup. | `repo/context_layer.py` → `should_retrieve()` selective gate |
| 2 | **ContextBench** — 2026 ([arXiv 2602.05892](https://arxiv.org/html/2602.05892v1)) | Benchmark context-retrieval quality with human gold contexts (1,136 tasks / 66 repos). | `evals/` retrieval **recall/precision vs gold_files** |
| 3 | **Repository Memory** — 2025 ([arXiv 2510.01003](https://arxiv.org/html/2510.01003v1)) | Agents should keep long-term repo memory (prior fixes, decisions), not solve each issue from scratch. | EverMind memory backend + `memory_lookup`; `SKILL.md` project rules |
| 4 | **LLavaCode** — 2025 ([arXiv 2510.19644](https://arxiv.org/abs/2510.19644)) | Compress retrieved code context → 20–38% TTFT reduction vs full-RAG. | `repo/context_layer.py` → `compress()` |
| 5 | **CodeRAG** — 2025 ([arXiv 2509.16112](https://arxiv.org/abs/2509.16112)) | Better query construction, multipath retrieval, BestFit reranking. | `localize()` scoring + rerank; the local model as repo-context router |
| 6 | **GraphCoder** — 2024 ([arXiv 2406.07003](https://arxiv.org/abs/2406.07003)) | Use code structure (defs/imports/calls), not dumb chunk embeddings; better match, less time/space. | `localize()` scores by **symbol/import** overlap, not just text |
| 7 | **RepoCoder** — Zhang et al., 2023 ([arXiv 2303.12570](https://arxiv.org/abs/2303.12570)) | Repo-level context spans files; iterative retrieval+generation; RepoEval. | the repo-aware retrieval foundation (`RepoContextLayer`) |
| 8 | **Small LMs for Code Generation** — 2025 ([arXiv 2507.03160](https://arxiv.org/html/2507.03160v2)) | 0.4B–10B models are viable for code sub-tasks (classify, route, summarize, localize). | the local-model role: routing/search/summarize/localize, **not** replacing the frontier model |

## The defensible claim

Not "a small model replaces Claude Code." Rather: **a small local code model + skills
+ memory + selective retrieval reduces how often Claude Code / Codex must be
called, and how much context each call costs — without losing task success.**
The eval harness (`autopilot eval`) measures exactly that: tokens saved, frontier
calls avoided, cost saved, retrieval recall/precision vs gold, and tests still
passing. Eval results persist to Butterbase (`agent_runs`/`eval_runs`); durable
lessons to EverMind.
