from pathlib import Path

from autonomy.policy import load_policy_config


def test_load_policy_config(tmp_path: Path):
    path = tmp_path / "policy.json"
    path.write_text(
        '{"max_speed_mps": 6, "min_battery_for_motion_pct": 40, "geofence_abs_xy_limit_m": 80}',
        encoding="utf-8",
    )

    cfg = load_policy_config(path)

    assert cfg.max_speed_mps == 6
    assert cfg.min_battery_for_motion_pct == 40
    assert cfg.geofence_abs_xy_limit_m == 80
