from __future__ import annotations

import json
from pathlib import Path

from .models import PolicyConfig, RetryPolicy, TransportConfig


def load_policy_config(file_path: str | Path) -> PolicyConfig:
    path = Path(file_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return PolicyConfig(
        max_speed_mps=float(data.get("max_speed_mps", 8.0)),
        min_battery_for_motion_pct=float(data.get("min_battery_for_motion_pct", 25.0)),
        geofence_abs_xy_limit_m=float(data.get("geofence_abs_xy_limit_m", 100.0)),
    )


def load_transport_config(file_path: str | Path) -> TransportConfig:
    path = Path(file_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    retry_data = data.get("retry", {})
    retry = RetryPolicy(
        max_attempts=int(retry_data.get("max_attempts", 3)),
        backoff_s=float(retry_data.get("backoff_s", 0.2)),
    )
    return TransportConfig(
        endpoint_url=str(data["endpoint_url"]),
        timeout_s=float(data.get("timeout_s", 1.0)),
        auth_token=data.get("auth_token"),
        retry=retry,
    )
