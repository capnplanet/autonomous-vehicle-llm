from __future__ import annotations

from autonomy.models import VehicleState
from autonomy.perception import TelemetryPerceptionPipeline, TelemetrySchemaValidator
from autonomy.replay import DeterministicTelemetryReplay


def test_replay_yields_events_in_order_and_reset_replays_again():
    events = [
        {
            "vehicle_id": "veh-001",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "x": 1.0,
            "y": 1.0,
            "battery_pct": 90.0,
            "armed": True,
            "connected": True,
        },
        {
            "vehicle_id": "veh-001",
            "timestamp": "2026-03-01T12:00:01+00:00",
            "x": 2.0,
            "y": 2.0,
            "battery_pct": 89.0,
            "armed": True,
            "connected": True,
        },
    ]
    replay = DeterministicTelemetryReplay(events)

    first = replay.next_event()
    second = replay.next_event()
    exhausted = replay.next_event()

    assert first is not None and first["x"] == 1.0
    assert second is not None and second["x"] == 2.0
    assert exhausted is None

    replay.reset()
    replayed_first = replay.next_event()
    assert replayed_first is not None and replayed_first["x"] == 1.0


def test_replay_plugs_into_telemetry_pipeline():
    events = [
        {
            "vehicle_id": "veh-001",
            "timestamp": "2026-03-01T12:00:00+00:00",
            "x": 1.0,
            "y": 1.0,
            "lidar_obstacles": [{"x": 5.0, "y": 5.0, "radius_m": 1.0}],
            "battery_pct": 90.0,
            "armed": True,
            "connected": True,
        }
    ]
    replay = DeterministicTelemetryReplay(events)
    validator = TelemetrySchemaValidator("specs/events/telemetry.schema.json")
    pipeline = TelemetryPerceptionPipeline(replay.next_event, validator)
    state = VehicleState(
        vehicle_id="veh-001",
        x=0.0,
        y=0.0,
        battery_pct=100.0,
        armed=True,
        connected=True,
    )

    frame = pipeline.observe(state=state)

    assert len(frame.obstacles) == 1
    assert frame.obstacles[0].x == 5.0
