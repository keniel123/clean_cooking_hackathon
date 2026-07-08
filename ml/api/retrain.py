"""Non-blocking, single-flight continual-retrain manager for the ML service.

The retrain runs in-process on a background thread (reusing the already-loaded
torch runtime and cached feature tables), so it does not spawn a cold subprocess
and does not block inference: requests keep serving the current model, and the
model hot-swaps only once a better checkpoint is promoted.

Only one retrain runs at a time; overlapping triggers return ``already_running``.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from gridcook_model.training.continual_update import run_update

from . import model_store

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "job_id": None,
    "started_at": None,
    "finished_at": None,
    "last_result": None,
    "last_error": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status() -> dict[str, Any]:
    with _lock:
        snapshot = dict(_state)
    snapshot["model_version"] = model_store.model_version()
    return snapshot


def _run(job_id: str, source: str, cutoff: str, epochs: int) -> None:
    result: dict[str, Any] | None = None
    error: str | None = None
    try:
        result = run_update(source=source, cutoff=cutoff, epochs=epochs)
        if result.get("promoted"):
            # Hot-swap: next inference call serves the freshly promoted checkpoint.
            result["model_version"] = model_store.reload()
    except Exception as exc:  # noqa: BLE001 - surface any failure via status
        error = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            _state.update(
                running=False,
                finished_at=_now(),
                last_result=result,
                last_error=error,
            )


def trigger(source: str = "live", cutoff: str = "2025-06-23", epochs: int = 5) -> dict[str, Any]:
    """Start a retrain in the background if one is not already running."""
    with _lock:
        if _state["running"]:
            return {"status": "already_running", **dict(_state)}
        job_id = uuid.uuid4().hex[:8]
        _state.update(
            running=True,
            job_id=job_id,
            started_at=_now(),
            finished_at=None,
            last_error=None,
        )

    thread = threading.Thread(
        target=_run, args=(job_id, source, cutoff, epochs), name=f"retrain-{job_id}", daemon=True
    )
    thread.start()
    return {"status": "started", "job_id": job_id, "started_at": _state["started_at"]}
