"""Long-context memory layer — local file by default, EverMind/EverOS when keyed.

EverMind (a.k.a. "Revermind"; EverOS, https://docs.evermind.ai) is the memory OS:
add messages, flush extraction, then search returns COMPACT episode summaries +
profile attributes — not raw logs. That compactness is the same principle as the
RLM checks: recall returns a small bundle, so the parent/frontier model's context
stays tiny. The `memory_lookup` subtask calls `search` (a cheap API call, not a
frontier-model call); runs persist via `add`.

Interface:
    search(query, top_k=None) -> str        # compact recalled context ("" if none)
    add(messages: list[dict]) -> None        # messages: {role, content[, timestamp]}
    flush() -> None

`make_memory_backend(cfg)` returns EverMindMemoryBackend when EVEROS_API_KEY (or
EVERMIND_API_KEY) is set, else LocalMemoryBackend.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import DEFAULT, Config


class LocalMemoryBackend:
    """Offline default: a small append-only JSON memory with naive keyword recall.
    Enough to run the loop and demonstrate recall without a network/key."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> list[dict]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except json.JSONDecodeError:
                return []
        return []

    def add(self, messages: list[dict]) -> None:
        mem = self._read()
        for m in messages:
            mem.append({"content": m.get("content", ""), "role": m.get("role", "user")})
        self.path.write_text(json.dumps(mem[-500:]))  # bounded

    def flush(self) -> None:  # no async extraction locally
        return None

    def search(self, query: str, top_k: int | None = None) -> str:
        mem = self._read()
        terms = {w.lower() for w in query.split() if len(w) > 3}
        scored = []
        for m in mem:
            c = (m.get("content") or "")
            score = sum(1 for t in terms if t in c.lower())
            if score:
                scored.append((score, c))
        scored.sort(reverse=True)
        hits = [c for _, c in scored[: (top_k or 5)]]
        return "\n".join(f"- {h[:160]}" for h in hits)


class EverMindMemoryBackend:
    """EverOS REST. add/flush/search (method=hybrid). Returns compact summaries.
    Fails soft -> empty recall, so the agent still runs if the API is down."""

    def __init__(self, api_key: str, cfg: Config = DEFAULT) -> None:
        self.api_key = api_key
        self.base = cfg.sponsors.evermind_base_url.rstrip("/")
        self.user_id = cfg.sponsors.evermind_user_id
        self.method = cfg.sponsors.evermind_method
        self.default_top_k = cfg.sponsors.evermind_top_k

    def _post(self, path: str, body: dict) -> dict | None:
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except (urllib.error.URLError, json.JSONDecodeError):
            return None

    def add(self, messages: list[dict]) -> None:
        now = int(time.time() * 1000)
        msgs = [{"role": m.get("role", "user"), "content": m.get("content", ""),
                 "timestamp": m.get("timestamp", now)} for m in messages]
        # agent memory endpoint supports role=tool + tool_calls
        self._post("/api/v1/memories/agent", {"user_id": self.user_id, "messages": msgs})

    def flush(self) -> None:
        self._post("/api/v1/memories/agent/flush", {"user_id": self.user_id})

    def search(self, query: str, top_k: int | None = None) -> str:
        res = self._post("/api/v1/memories/search", {
            "query": query, "filters": {"user_id": self.user_id},
            "method": self.method, "top_k": top_k or self.default_top_k,
        })
        if not res:
            return ""
        # response shape varies; extract compact text from common fields
        data = res.get("data", res)
        memories = (data or {}).get("memories") or data.get("results") or []
        out: list[str] = []
        for m in memories if isinstance(memories, list) else []:
            text = (
                m.get("summary") or m.get("content") or m.get("text")
                or (m.get("episode") or {}).get("summary") or ""
            )
            if text:
                out.append(f"- {str(text)[:200]}")
        return "\n".join(out[: (top_k or self.default_top_k)])


def make_memory_backend(cfg: Config = DEFAULT, local_path: Path | None = None):
    key = os.environ.get(cfg.sponsors.evermind_api_key_env, "") or os.environ.get("EVERMIND_API_KEY", "")
    if key:
        return EverMindMemoryBackend(key, cfg)
    return LocalMemoryBackend(local_path or (Path(cfg.paths.out) / "memory" / "local_memory.json"))


def memory_backend_name(backend) -> str:
    return type(backend).__name__
