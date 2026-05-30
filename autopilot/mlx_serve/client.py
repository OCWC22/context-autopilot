"""OpenAI-compatible client for the local MLX server, exposed as an RLM sub-LM.

Stdlib-only (urllib) so importing this never pulls a heavy dependency. The
returned callable matches the `SubLM` signature used by the RLM inspector:
`(query, context_slice) -> str`. If the local server isn't reachable it raises a
clear error telling you to start it (or use the 'stub' backend offline).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

SubLM = Callable[[str, str], str]

_SYSTEM = (
    "You are a precise engineering-check sub-model. You are given a QUERY and a "
    "SLICE of a larger artifact (log, config, code, or trace). Answer ONLY about "
    "this slice, in at most 3 short lines, quoting the exact offending text. If "
    "the slice has nothing relevant, reply exactly 'none'. Do not speculate."
)


def mlx_sub_lm(
    model: str | None = None,
    base_url: str = "http://127.0.0.1:8080/v1",
    temperature: float = 0.0,
    max_tokens: int = 256,
    timeout: float = 60.0,
) -> SubLM:
    url = base_url.rstrip("/") + "/chat/completions"

    def call(query: str, context_slice: str) -> str:
        payload = {
            "model": model or "local",
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"QUERY: {query}\n\nSLICE:\n{context_slice}"},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"local MLX server unreachable at {base_url} ({e}). Start it with "
                "`python -m autopilot.mlx_serve.server` or use sub_lm='stub' offline."
            ) from e
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return ""

    return call
