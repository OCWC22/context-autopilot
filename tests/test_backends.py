"""Sponsor backend tests (offline): local round-trips + env auto-selection.
Butterbase (state) and EverMind/"Revermind" (memory) clients are constructed but
not network-hit here; only the local backends are exercised end-to-end."""

from __future__ import annotations

import importlib

from autopilot.config import DEFAULT
from autopilot.agent.state_backend import (
    LocalStateBackend, ButterbaseStateBackend, make_state_backend, state_backend_name,
)
from autopilot.agent.memory_backend import (
    LocalMemoryBackend, EverMindMemoryBackend, make_memory_backend, memory_backend_name,
)


def test_local_state_roundtrip(tmp_path):
    sb = LocalStateBackend(tmp_path / "state")
    sb.log_event("run1", {"kind": "plan", "tier": "local"})
    sb.put("k", {"a": 1})
    assert sb.get("k") == {"a": 1}
    sb.save_run("run1", {"goal": "x", "result": "y"})
    assert (tmp_path / "state" / "events.jsonl").exists()


def test_local_memory_recall(tmp_path):
    mb = LocalMemoryBackend(tmp_path / "mem.json")
    assert mb.search("coffee preference") == ""          # empty at first
    mb.add([{"role": "user", "content": "User prefers black coffee, no sugar"}])
    mb.flush()
    hits = mb.search("coffee preference")
    assert "coffee" in hits.lower()                        # recalled next time


def test_state_backend_autoselect(monkeypatch):
    monkeypatch.delenv("BUTTERBASE_APP_ID", raising=False)
    monkeypatch.delenv("BUTTERBASE_API_KEY", raising=False)
    assert isinstance(make_state_backend(DEFAULT), LocalStateBackend)
    monkeypatch.setenv("BUTTERBASE_APP_ID", "app_x")
    monkeypatch.setenv("BUTTERBASE_API_KEY", "bb_sk_x")
    assert isinstance(make_state_backend(DEFAULT), ButterbaseStateBackend)


def test_memory_backend_autoselect(monkeypatch):
    monkeypatch.delenv("EVEROS_API_KEY", raising=False)
    monkeypatch.delenv("EVERMIND_API_KEY", raising=False)
    assert isinstance(make_memory_backend(DEFAULT), LocalMemoryBackend)
    monkeypatch.setenv("EVEROS_API_KEY", "ev_x")
    assert isinstance(make_memory_backend(DEFAULT), EverMindMemoryBackend)
