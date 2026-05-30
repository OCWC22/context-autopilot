"""Selective, structure-aware repo context retrieval + compression.

Pipeline per query:
  should_retrieve?  (Repoformer gate) -> localize (GraphCoder-lite symbol/import
  scoring + CodeRAG-style rerank) -> compress (LLavaCode-style) -> compact context.

Memory (prior decisions/fixes) is recalled from the EverMind backend and SKILL.md
project rules are loaded once, so the model doesn't relearn the repo each session.
Deterministic + stdlib so it runs offline; a local model can rerank/compress when
available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".sql",
             ".yml", ".yaml", ".toml", ".json", ".md", "Dockerfile"}
_DEF_RE = re.compile(r"^\s*(def|class|func|function|type|interface|const|export)\s+([A-Za-z_][\w]*)", re.M)
_IMPORT_RE = re.compile(r"^\s*(import|from|require|use|#include)\b.*", re.M)
_RETRIEVE_HINTS = re.compile(
    r"\b(file|files|function|class|method|module|import|test|tests|bug|error|fix|"
    r"refactor|where|which|locate|implement|endpoint|route|config|schema|deploy)\b", re.I)


@dataclass
class FileScore:
    path: str
    score: float
    why: str = ""


@dataclass
class RetrievalResult:
    query: str
    retrieved: list[FileScore] = field(default_factory=list)
    compact_context: str = ""
    should_retrieve: bool = True
    skills_used: bool = False
    memory_used: bool = False
    context_chars: int = 0      # raw chars of retrieved files
    compact_chars: int = 0      # chars handed onward (compressed)

    @property
    def files(self) -> list[str]:
        return [f.path for f in self.retrieved]

    @property
    def compression_ratio(self) -> float:
        return round(self.context_chars / self.compact_chars, 1) if self.compact_chars else 0.0


class RepoContextLayer:
    def __init__(self, repo: str | Path, local_model=None, rlm=None, memory_backend=None) -> None:
        self.repo = Path(repo)
        self.model = local_model      # optional rerank/compress (LocalModel)
        self.rlm = rlm                # optional RLMInspector for compression
        self.memory = memory_backend  # EverMind/local
        self._skill_text: str | None = None

    # --- SKILL.md: project rules loaded once (don't relearn each session) ---

    def load_skills(self) -> str:
        if self._skill_text is not None:
            return self._skill_text
        for cand in (self.repo / ".autopilot" / "SKILL.md", self.repo / "SKILL.md",
                     self.repo / "AGENTS.md", self.repo / "CLAUDE.md"):
            if cand.is_file():
                self._skill_text = cand.read_text(errors="ignore")[:8000]
                return self._skill_text
        self._skill_text = ""
        return self._skill_text

    # --- Repoformer gate: is retrieval worth it? ---

    def should_retrieve(self, query: str) -> bool:
        # Short, generic, or self-contained queries don't need repo context.
        if len(query) < 12:
            return False
        return bool(_RETRIEVE_HINTS.search(query))

    # --- localize: rank files by symbol/import/keyword overlap (structure-aware) ---

    def _candidate_files(self) -> list[Path]:
        out = []
        for f in self.repo.rglob("*"):
            if not f.is_file():
                continue
            if any(part in {".git", "node_modules", "__pycache__", "autopilot_out",
                            ".venv", "venv", "dist", "build"} for part in f.parts):
                continue
            if f.suffix in _CODE_EXT or f.name in _CODE_EXT:
                out.append(f)
        return out

    def localize(self, query: str, top_k: int = 5) -> list[FileScore]:
        terms = {t.lower() for t in re.findall(r"[A-Za-z_][\w]{2,}", query)}
        if not terms:
            return []
        scored: list[FileScore] = []
        for f in self._candidate_files():
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            low = text.lower()
            name_hit = sum(2 for t in terms if t in f.name.lower())          # path signal
            defs = {m.group(2).lower() for m in _DEF_RE.finditer(text)}
            def_hit = sum(3 for t in terms if t in defs)                     # symbol signal (GraphCoder)
            imp_hit = 1 if any(t in (m.group(0).lower()) for m in _IMPORT_RE.finditer(text) for t in terms) else 0
            body_hit = sum(1 for t in terms if t in low)                     # keyword signal
            score = name_hit + def_hit + imp_hit + min(body_hit, 5)
            if score > 0:
                why = []
                if name_hit: why.append("path")
                if def_hit: why.append("symbol")
                if imp_hit: why.append("import")
                if body_hit: why.append("keyword")
                scored.append(FileScore(str(f.relative_to(self.repo)), float(score), "+".join(why)))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    # --- compress: compact the selected files (LLavaCode-style) ---

    def compress(self, files: list[str], query: str) -> tuple[str, int]:
        raw_total = 0
        parts: list[str] = []
        for rel in files:
            p = self.repo / rel
            try:
                text = p.read_text(errors="ignore")
            except OSError:
                continue
            raw_total += len(text)
            if self.rlm is not None:
                from ..checks.rlm_runtime import ContextItem
                res = self.rlm.inspect(f"Extract only what's relevant to: {query}", [ContextItem(rel, text)])
                summary = res.answer
            else:
                # deterministic compression: signatures + matching lines
                sigs = [m.group(0).strip() for m in _DEF_RE.finditer(text)][:12]
                terms = {t.lower() for t in re.findall(r"[A-Za-z_][\w]{2,}", query)}
                lines = [ln.strip() for ln in text.splitlines() if any(t in ln.lower() for t in terms)][:8]
                summary = "  " + "\n  ".join(sigs + lines) if (sigs or lines) else "(no salient lines)"
            parts.append(f"### {rel}\n{summary}")
        compact = "\n\n".join(parts)
        return compact, raw_total

    # --- answer: the full selective-retrieval flow ---

    def answer(self, query: str, top_k: int = 5) -> RetrievalResult:
        res = RetrievalResult(query=query)
        skills = self.load_skills()
        res.skills_used = bool(skills)

        if not self.should_retrieve(query):
            res.should_retrieve = False
            res.compact_context = "(no repo retrieval needed)"
            return res

        res.retrieved = self.localize(query, top_k=top_k)
        compact, raw_total = self.compress(res.files, query)
        res.context_chars = raw_total

        mem = ""
        if self.memory is not None:
            mem = self.memory.search(query) or ""
            res.memory_used = bool(mem)

        header = ""
        if skills:
            header += "PROJECT RULES (SKILL.md):\n" + skills[:600] + "\n\n"
        if mem:
            header += "PRIOR DECISIONS (memory):\n" + mem[:600] + "\n\n"
        res.compact_context = header + "RELEVANT CODE:\n" + compact
        res.compact_chars = len(res.compact_context)
        return res
