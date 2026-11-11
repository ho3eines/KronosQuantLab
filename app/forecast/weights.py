"""Inspect and download Kronos checkpoints, showing license and size *before* downloading."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.core.config import MODELS, MODELS_DIR, TOKENIZER, ModelSpec
from app.core.errors import ModelUnavailableError

log = logging.getLogger(__name__)
MANIFEST = "kql_manifest.json"
SAFETY_MARGIN_BYTES = 2 * 1024**3  # keep 2 GiB free after the download


def all_specs() -> list[ModelSpec]:
    return [TOKENIZER, *MODELS.values()]


def _hf_api() -> Any:
    try:
        from huggingface_hub import HfApi
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailableError(f"huggingface_hub is not installed: {exc}") from exc
    return HfApi()


def inspect_repo(spec: ModelSpec, api: Any | None = None) -> dict[str, Any]:
    """Metadata only (no weight download): resolved commit, license, file list and sizes."""
    api = api or _hf_api()
    try:
        info = api.model_info(spec.repo_id, revision=spec.revision, files_metadata=True)
    except Exception as exc:  # noqa: BLE001 - network / auth / missing repo
        raise ModelUnavailableError(f"cannot read {spec.repo_id}: {type(exc).__name__}: {exc}") from exc
    card = getattr(info, "card_data", None)
    license_id = getattr(card, "license", None) if card is not None else None
    files = [{"name": s.rfilename, "bytes": getattr(s, "size", None)} for s in (info.siblings or [])]
    return {
        "repo_id": spec.repo_id,
        "requested_revision": spec.revision,
        "resolved_sha": info.sha,
        "license": license_id,  # None means: the model card declares no license
        "files": files,
        "total_bytes": sum(f["bytes"] or 0 for f in files),
    }


def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists():
        probe = probe.parent
    return shutil.disk_usage(probe).free


def check_space(total_bytes: int, free: int) -> None:
    if total_bytes + SAFETY_MARGIN_BYTES > free:
        raise ModelUnavailableError(
            f"not enough disk space: need {total_bytes / 1e9:.2f} GB plus a 2 GiB margin, "
            f"free {free / 1e9:.2f} GB. Nothing was downloaded."
        )


def download(spec: ModelSpec, meta: dict[str, Any]) -> Path:
    """Download exactly the inspected commit and record a manifest next to the weights."""
    from huggingface_hub import snapshot_download

    target = spec.local_dir
    snapshot_download(repo_id=spec.repo_id, revision=meta["resolved_sha"], local_dir=str(target))
    (target / MANIFEST).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return target


def read_manifest(spec: ModelSpec) -> dict[str, Any] | None:
    path = spec.local_dir / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def models_dir() -> Path:
    return MODELS_DIR
