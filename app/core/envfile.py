"""Minimal ``.env`` support for ``KQL_*`` settings, without adding a dependency.

The project reads its settings from the process environment.  A local ``.env``
file is a convenience for interactive use: it is parsed once at import time by
``app.core.config`` and copied into ``os.environ``.

Rules, deliberately boring:

* only keys that start with ``KQL_`` are considered (a stray ``PATH=`` line can
  never change how the process runs);
* an environment variable that is already set always wins, so a one-off
  ``$env:KQL_...`` or a CI value is never silently replaced by the file;
* ``KEY=VALUE``, optional ``export`` prefix, optional surrounding quotes and
  trailing ``# comments`` are accepted; anything else is ignored;
* the file is optional and a missing/unreadable file is not an error.

Nothing here is a secret store: the project needs no API keys, and the file is
git-ignored.
"""
from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

PREFIX = "KQL_"
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env(text: str) -> dict[str, str]:
    """Parse ``.env`` text into the ``KQL_*`` key/value pairs it defines."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.startswith(PREFIX) or len(key) == len(PREFIX) or not _KEY.fullmatch(key):
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            for marker in (" #", "\t#"):
                if marker in value:
                    value = value.split(marker, 1)[0].rstrip()
                    break
        values[key] = value
    return values


def load_env_file(path: Path | str, environ: MutableMapping[str, str] | None = None) -> dict[str, str]:
    """Copy the file's ``KQL_*`` values into ``environ`` without overriding it.

    Returns the pairs that were actually applied (useful for tests and for a
    ``--verbose`` style report).  A missing file simply applies nothing.
    """
    target = os.environ if environ is None else environ
    file = Path(path)
    if not file.is_file():
        return {}
    try:
        text = file.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    parsed = parse_env(text)
    applied = {key: value for key, value in parsed.items() if key not in target}
    target.update(applied)
    return applied
