"""Minimal JSON-over-HTTPS helper shared by the public market-data adapters.

Only GET is offered: this project reads public candles and never sends an order,
a credential or an account command over the network.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

USER_AGENT = "KronosQuantLab-research"


def get_json(url: str, timeout: float = 30.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https hosts
        return json.loads(resp.read().decode("utf-8"))
