"""Write per-run JSON artifacts under outputs/runs/{run_id}/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import RUNS_DIR


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def save_run_artifacts(result: dict, run_id: str | None = None) -> Path:
    run_id = run_id or new_run_id()
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    metrics = result.get("metrics") or {}
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[artifacts] saved run {run_id} → {run_dir}", flush=True)
    return run_dir
