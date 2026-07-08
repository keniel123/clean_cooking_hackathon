"""Filesystem checkpoint registry with monotonically increasing model versions.

Layout (default ``ml/checkpoints``, override with GRIDCOOK_CHECKPOINTS):

    checkpoints/<model_name>/nn-v1.pt
    checkpoints/<model_name>/nn-v2.pt
    checkpoints/<model_name>/manifest.json   # {"current": "nn-v2", "versions": [...]}

Each ``.pt`` bundles the model config, weights, and metadata (metrics, the
feature standardizer, and feature columns) so it can be rebuilt and served
without any other state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import torch
from torch import nn

_MODULE_DIR = Path(__file__).resolve().parents[2]  # ml/
_DEFAULT_CHECKPOINTS = _MODULE_DIR / "checkpoints"

VERSION_PREFIX = "nn-v"


def checkpoints_dir() -> Path:
    override = os.environ.get("GRIDCOOK_CHECKPOINTS")
    return Path(override) if override else _DEFAULT_CHECKPOINTS


def _model_dir(model_name: str) -> Path:
    return checkpoints_dir() / model_name


def _manifest_path(model_name: str) -> Path:
    return _model_dir(model_name) / "manifest.json"


def _read_manifest(model_name: str) -> dict[str, Any]:
    path = _manifest_path(model_name)
    if not path.exists():
        return {"current": None, "versions": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(model_name: str, manifest: dict[str, Any]) -> None:
    _manifest_path(model_name).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _next_version(manifest: dict[str, Any]) -> str:
    return f"{VERSION_PREFIX}{len(manifest['versions']) + 1}"


def list_versions(model_name: str) -> list[str]:
    return list(_read_manifest(model_name)["versions"])


def latest_version(model_name: str) -> str | None:
    return _read_manifest(model_name)["current"]


def save_checkpoint(model_name: str, module: nn.Module, metadata: dict[str, Any]) -> str:
    """Persist a new version of ``model_name`` and mark it current. Returns version."""
    model_dir = _model_dir(model_name)
    model_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(model_name)
    version = _next_version(manifest)

    payload = {
        "model_class": module.__class__.__name__,
        "config": getattr(module, "config", {}),
        "state_dict": module.state_dict(),
        "metadata": {**metadata, "model_version": version},
    }
    torch.save(payload, model_dir / f"{version}.pt")

    manifest["versions"].append(version)
    manifest["current"] = version
    _write_manifest(model_name, manifest)
    return version


def load_checkpoint(model_name: str, model_class: type[nn.Module],
                    version: str | None = None) -> tuple[nn.Module, dict[str, Any]]:
    """Rebuild a model from a checkpoint. Defaults to the current version."""
    version = version or latest_version(model_name)
    if version is None:
        raise FileNotFoundError(f"No checkpoints found for model '{model_name}'")
    payload = torch.load(_model_dir(model_name) / f"{version}.pt", weights_only=False)
    module = model_class(**payload["config"])
    module.load_state_dict(payload["state_dict"])
    module.eval()
    return module, payload["metadata"]
