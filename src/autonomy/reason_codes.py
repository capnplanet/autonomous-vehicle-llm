from __future__ import annotations

from collections.abc import Iterable


_REASON_MAP: dict[str, str] = {
    "vehicle disconnected": "vehicle_disconnected",
    "localization uncertainty above threshold": "localization_uncertainty_high",
    "sensor data stale": "sensor_data_stale",
    "speed exceeds policy": "speed_exceeds_policy",
    "battery below motion threshold": "battery_below_motion_threshold",
    "obstacle standoff violated": "obstacle_standoff_violated",
    "missing move target": "missing_move_target",
    "target x out of geofence": "target_x_out_of_geofence",
    "target y out of geofence": "target_y_out_of_geofence",
    "cannot disarm away from home": "cannot_disarm_away_from_home",
    "localization_stale": "localization_stale",
    "subsystem_failure": "subsystem_failure",
    "adapter_speed_limit": "adapter_speed_limit",
    "adapter_capability_unsupported": "adapter_capability_unsupported",
    "transport_failure": "transport_failure",
    "unknown": "unknown_policy_violation",
}


def to_policy_reason_code(reason: str) -> str:
    normalized = reason.strip().lower()
    return _REASON_MAP.get(normalized, _slugify_reason(normalized))


def extract_policy_reason_codes(events: Iterable[str]) -> list[str]:
    codes: list[str] = []
    for event in events:
        if not event.startswith("policy_block:"):
            continue
        raw_reason = event.split(":", 1)[1]
        codes.append(to_policy_reason_code(raw_reason))
    return codes


def _slugify_reason(reason: str) -> str:
    output_chars: list[str] = []
    previous_underscore = False
    for char in reason:
        if char.isalnum():
            output_chars.append(char.lower())
            previous_underscore = False
            continue
        if not previous_underscore:
            output_chars.append("_")
            previous_underscore = True

    value = "".join(output_chars).strip("_")
    if not value:
        return "unknown_policy_violation"
    return value
