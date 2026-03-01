from __future__ import annotations

from datetime import UTC, datetime, timedelta

from autonomy.errors import AdapterExecutionError
from autonomy.models import VehicleState
from autonomy.replay import DeterministicTelemetryReplay
from autonomy.perception import TelemetryPerceptionPipeline, TelemetrySchemaValidator


def _state() -> VehicleState:
    return VehicleState(
        vehicle_id="veh-001",
        x=0.0,
        y=0.0,
        battery_pct=90.0,
        armed=True,
        connected=True,
    )


def _valid_event() -> dict[str, object]:
    return {
        "vehicle_id": "veh-001",
        "timestamp": "2026-03-01T12:00:00+00:00",
        "x": 1.0,
        "y": 2.0,
        "gps_x": 1.2,
        "gps_y": 2.1,
        "imu_vx_mps": 0.5,
        "imu_vy_mps": 0.1,
        "heading_rad": 0.2,
        "position_std_m": 0.4,
        "lidar_obstacles": [
            {"x": 2.0, "y": 3.0, "radius_m": 0.7, "confidence": 0.8, "source": "lidar"}
        ],
        "battery_pct": 85.0,
        "armed": True,
        "connected": True,
    }


def test_validator_accepts_valid_telemetry_event():
    validator = TelemetrySchemaValidator("specs/events/telemetry.schema.json")
    validator.validate(_valid_event())


def test_validator_rejects_unknown_property():
    validator = TelemetrySchemaValidator("specs/events/telemetry.schema.json")
    event = _valid_event()
    event["unknown"] = "value"

    try:
        validator.validate(event)
    except AdapterExecutionError as exc:
        assert "unexpected field" in str(exc)
    else:
        raise AssertionError("expected schema validation error")


def test_pipeline_emits_perception_frame_with_lidar_obstacles():
    validator = TelemetrySchemaValidator("specs/events/telemetry.schema.json")
    source = lambda: _valid_event()
    pipeline = TelemetryPerceptionPipeline(source, validator)

    frame = pipeline.observe(_state())

    assert len(frame.obstacles) == 1
    assert frame.obstacles[0].radius_m == 0.7
    assert frame.sensor_health["gps"] is True
    assert frame.sensor_health["imu"] is True
    assert frame.sensor_health["lidar"] is True
    assert frame.tracking_summary["tracked_count"] == 1


def test_pipeline_normalizes_percentage_confidence_and_tracks_objects():
    now = datetime.now(UTC)
    events = [
        {
            "vehicle_id": "veh-001",
            "timestamp": now.isoformat(),
            "x": 0.0,
            "y": 0.0,
            "lidar_obstacles": [
                {
                    "x": 2.0,
                    "y": 1.0,
                    "radius_m": 0.5,
                    "confidence": 80,
                    "source": "lidar",
                    "class_label": "cone",
                }
            ],
            "battery_pct": 90.0,
            "armed": True,
            "connected": True,
        },
        {
            "vehicle_id": "veh-001",
            "timestamp": (now + timedelta(seconds=1)).isoformat(),
            "x": 0.0,
            "y": 0.0,
            "lidar_obstacles": [
                {
                    "x": 3.0,
                    "y": 1.0,
                    "radius_m": 0.5,
                    "confidence": 0.6,
                    "source": "lidar",
                    "class_label": "cone",
                }
            ],
            "battery_pct": 90.0,
            "armed": True,
            "connected": True,
        },
    ]
    replay = DeterministicTelemetryReplay(events)
    validator = TelemetrySchemaValidator("specs/events/telemetry.schema.json")
    pipeline = TelemetryPerceptionPipeline(replay.next_event, validator)

    first = pipeline.observe(_state())
    second = pipeline.observe(_state())

    assert first.obstacles[0].confidence == 0.8
    assert first.obstacles[0].track_id is not None
    assert second.obstacles[0].track_id == first.obstacles[0].track_id
    assert round(second.obstacles[0].vx_mps or 0.0, 2) == 1.0
    assert second.obstacles[0].class_label == "cone"
