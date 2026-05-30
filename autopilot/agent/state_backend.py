"""Agent database / state layer — local disk by default, Butterbase when keyed.

Holds the externalized agent state: the per-run event log, run records, and
key/value agent state (the `state_update` subtask writes here). Keeping this
OUTSIDE the model is the point — the frontier model never reloads it.

Backends share a tiny interface:
    log_event(run_id, event: dict) -> None
    save_run(run_id, payload: dict) -> None
    put(key, value) -> None
    get(key) -> Any | None

`make_state_backend(cfg)` returns ButterbaseStateBackend when
BUTTERBASE_API_KEY + BUTTERBASE_APP_ID are set, else LocalStateBackend.
Butterbase REST Data API: https://docs.butterbase.ai/sdks-and-tools/rest-api/
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..config import DEFAULT, Config


class LocalStateBackend:
    """Disk-backed (offline default). Events -> events.jsonl, KV -> kv.json."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._kv_path = self.root / "kv.json"

    def log_event(self, run_id: str, event: dict) -> None:
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"run_id": run_id, **event}) + "\n")

    def save_run(self, run_id: str, payload: dict) -> None:
        (self.root / "result.json").write_text(json.dumps(payload, indent=2))

    def put(self, key: str, value: Any) -> None:
        kv = self._read_kv()
        kv[key] = value
        self._kv_path.write_text(json.dumps(kv))

    def get(self, key: str) -> Any | None:
        return self._read_kv().get(key)

    def _read_kv(self) -> dict:
        if self._kv_path.exists():
            try:
                return json.loads(self._kv_path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}


class ButterbaseStateBackend:
    """Butterbase REST Data API. Append rows to the events/runs tables and store
    KV agent state in a key/value table. Fails soft (logs nothing, returns None)
    so a transient API error never sinks the agent run.

    Expected schema (apply once via Butterbase schema tools / dashboard):
      agent_events(id uuid pk default gen_random_uuid(), run_id text, kind text,
                   tier text, payload jsonb, created_at timestamptz default now())
      agent_runs(id uuid pk default gen_random_uuid(), run_id text unique,
                 payload jsonb, created_at timestamptz default now())
      agent_state(key text primary, value jsonb)
    """

    def __init__(self, app_id: str, api_key: str, cfg: Config = DEFAULT) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.base = cfg.sponsors.butterbase_base_url.rstrip("/")
        self.s = cfg.sponsors
        self.ok = True

    def _url(self, table: str, row_id: str | None = None) -> str:
        u = f"{self.base}/v1/{self.app_id}/{table}"
        return f"{u}/{row_id}" if row_id else u

    def _req(self, method: str, url: str, body: dict | None = None) -> Any | None:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except (urllib.error.URLError, json.JSONDecodeError):
            self.ok = False
            return None

    def log_event(self, run_id: str, event: dict) -> None:
        self._req("POST", self._url(self.s.butterbase_events_table), {
            "run_id": run_id, "kind": event.get("kind"), "tier": event.get("tier"),
            "payload": event,
        })

    def save_run(self, run_id: str, payload: dict) -> None:
        self._req("POST", self._url(self.s.butterbase_runs_table), {
            "run_id": run_id, "payload": payload,
        })

    def put(self, key: str, value: Any) -> None:
        self._req("POST", self._url(self.s.butterbase_state_table), {
            "key": key, "value": value,
        })

    def get(self, key: str) -> Any | None:
        rows = self._req("GET", self._url(self.s.butterbase_state_table) + f"?key=eq.{key}")
        if isinstance(rows, list) and rows:
            return rows[0].get("value")
        if isinstance(rows, dict):
            return rows.get("value")
        return None


def make_state_backend(cfg: Config = DEFAULT, local_root: Path | None = None):
    app_id = os.environ.get(cfg.sponsors.butterbase_app_id_env, "")
    api_key = os.environ.get(cfg.sponsors.butterbase_api_key_env, "")
    if app_id and api_key:
        return ButterbaseStateBackend(app_id, api_key, cfg)
    return LocalStateBackend(local_root or (Path(cfg.paths.out) / "state"))


def state_backend_name(backend: Any) -> str:
    return type(backend).__name__
