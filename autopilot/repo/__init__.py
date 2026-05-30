"""Repo-aware local context layer.

A small/local model + RLM that understands the repo (structure, files,
conventions, prior decisions) and does SELECTIVE retrieval — deciding whether
context is needed, which files, and compressing them — instead of indexing and
re-stuffing the whole codebase into a frontier prompt every time.

Grounding (see CITATIONS.md):
- Repoformer (Wu et al., ICML 2024): learn WHEN retrieval is needed; skip it
  when it doesn't help. Our `should_retrieve` gate.
- RepoCoder (Zhang et al., 2023): repo-level context spans files; retrieve it.
- GraphCoder (2024): use code structure (defs/imports/calls), not dumb chunks.
  Our localizer scores by symbol/import overlap, not just text.
- CodeRAG (2025): better queries + reranking. Our localizer reranks candidates.
- LLavaCode (2025): compress retrieved context to cut TTFT/tokens. Our `compress`.
- Repository Memory (2025): remember prior fixes/decisions. Folded in via the
  EverMind memory backend + SKILL.md.
"""

from .context_layer import RepoContextLayer, RetrievalResult  # noqa: F401
from .indexer import RepoIndexer, RepoIndex  # noqa: F401
from .watch import RepoWatcher  # noqa: F401
from .dag import DAGBuilder, RepoDAG  # noqa: F401
from .bundle import build_bundle  # noqa: F401
