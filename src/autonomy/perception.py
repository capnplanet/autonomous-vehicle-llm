from __future__ import annotations

import json
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .errors import AdapterExecutionError
from .models import VehicleState


@dataclass(slots=True)
class DetectedObstacle:
    x: float
    y: float
    radius_m: float
    confidence: float = 1.0
    source: str = "unknown"
    track_id: str | None = None
    class_label: str = "unknown"
    vx_mps: float | None = None
    vy_mps: float | None = None
    age_frames: int = 1


@dataclass(slots=True)
class PerceptionFrame:
    timestamp_s: float
    obstacles: list[DetectedObstacle] = field(default_factory=list)
    sensor_health: dict[str, bool] = field(default_factory=dict)
    telemetry: dict[str, object] = field(default_factory=dict)
    tracking_summary: dict[str, int | float] = field(default_factory=dict)


@dataclass(slots=True)
class _TrackState:
    x: float
    y: float
    timestamp_s: float
    source: str
    age_frames: int


class DeterministicObstacleTracker:
    def __init__(self, max_association_distance_m: float = 3.0, max_track_age_s: float = 2.0) -> None:
        self.max_association_distance_m = max(0.0, max_association_distance_m)
        self.max_track_age_s = max(0.0, max_track_age_s)
        self._tracks: dict[str, _TrackState] = {}
        self._counter = 1

    def update(self, obstacles: list[DetectedObstacle], timestamp_s: float) -> list[DetectedObstacle]:
        self._prune_expired(timestamp_s)
        assigned_track_ids: set[str] = set()
        tracked: list[DetectedObstacle] = []

        for obstacle in obstacles:
            track_id = self._assign_track_id(obstacle, assigned_track_ids)
            previous = self._tracks.get(track_id)
            velocity_x, velocity_y = self._estimate_velocity(previous, obstacle, timestamp_s)
            age_frames = (previous.age_frames + 1) if previous is not None else 1

            tracked.append(
                DetectedObstacle(
                    x=obstacle.x,
                    y=obstacle.y,
                    radius_m=obstacle.radius_m,
                    confidence=obstacle.confidence,
                    source=obstacle.source,
                    track_id=track_id,
                    class_label=obstacle.class_label,
                    vx_mps=velocity_x,
                    vy_mps=velocity_y,
                    age_frames=age_frames,
                )
            )

            self._tracks[track_id] = _TrackState(
                x=obstacle.x,
                y=obstacle.y,
                timestamp_s=timestamp_s,
                source=obstacle.source,
                age_frames=age_frames,
            )
            assigned_track_ids.add(track_id)

        return tracked

    def _prune_expired(self, timestamp_s: float) -> None:
        expired = [
            track_id
            for track_id, state in self._tracks.items()
            if timestamp_s - state.timestamp_s > self.max_track_age_s
        ]
        for track_id in expired:
            self._tracks.pop(track_id, None)

    def _assign_track_id(self, obstacle: DetectedObstacle, assigned_track_ids: set[str]) -> str:
        if obstacle.track_id:
            return obstacle.track_id

        associated = self._nearest_associated_track(obstacle, assigned_track_ids)
        if associated is not None:
            return associated

        new_id = f"{obstacle.source}-{self._counter:04d}"
        self._counter += 1
        return new_id

    def _nearest_associated_track(self, obstacle: DetectedObstacle, assigned_track_ids: set[str]) -> str | None:
        candidates: list[tuple[float, str]] = []
        for track_id, state in self._tracks.items():
            if track_id in assigned_track_ids:
                continue
            if state.source != obstacle.source:
                continue
            distance = math.dist((obstacle.x, obstacle.y), (state.x, state.y))
            if distance <= self.max_association_distance_m:
                candidates.append((distance, track_id))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][1]

    def _estimate_velocity(
        self,
        previous: _TrackState | None,
        obstacle: DetectedObstacle,
        timestamp_s: float,
    ) -> tuple[float | None, float | None]:
        if previous is None:
            return None, None
        dt = timestamp_s - previous.timestamp_s
        if dt <= 0.0:
            return None, None
        return (obstacle.x - previous.x) / dt, (obstacle.y - previous.y) / dt


class PerceptionPipeline(ABC):
    @abstractmethod
    def observe(self, state: VehicleState) -> PerceptionFrame:
        raise NotImplementedError


class NullPerceptionPipeline(PerceptionPipeline):
    def observe(self, state: VehicleState) -> PerceptionFrame:
        return PerceptionFrame(timestamp_s=time.time())


class TelemetrySchemaValidator:
    def __init__(self, schema_path: str | Path) -> None:
        self.schema_path = Path(schema_path)
        self.schema = json.loads(self.schema_path.read_text(encoding="utf-8"))

    def validate(self, payload: dict[str, object]) -> None:
        self._validate_node(payload, self.schema, path="$")

    def _validate_node(self, value: object, schema: dict[str, object], path: str) -> None:
        expected_type = schema.get("type")
        if expected_type == "object":
            if not isinstance(value, dict):
                raise AdapterExecutionError(f"schema validation failed at {path}: expected object")
            self._validate_object(value, schema, path)
            return

        if expected_type == "array":
            if not isinstance(value, list):
                raise AdapterExecutionError(f"schema validation failed at {path}: expected array")
            self._validate_array(value, schema, path)
            return

        if expected_type == "string":
            if not isinstance(value, str):
                raise AdapterExecutionError(f"schema validation failed at {path}: expected string")
            if schema.get("format") == "date-time":
                self._parse_timestamp(value)
            return

        if expected_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise AdapterExecutionError(f"schema validation failed at {path}: expected number")
            minimum = schema.get("minimum")
            if isinstance(minimum, (int, float)) and float(value) < float(minimum):
                raise AdapterExecutionError(f"schema validation failed at {path}: below minimum")
            maximum = schema.get("maximum")
            if isinstance(maximum, (int, float)) and float(value) > float(maximum):
                raise AdapterExecutionError(f"schema validation failed at {path}: above maximum")
            return

        if expected_type == "boolean":
            if not isinstance(value, bool):
                raise AdapterExecutionError(f"schema validation failed at {path}: expected boolean")
            return

        raise AdapterExecutionError(f"unsupported schema type at {path}: {expected_type}")

    def _validate_object(self, value: dict[str, object], schema: dict[str, object], path: str) -> None:
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    raise AdapterExecutionError(f"schema validation failed at {path}: missing '{key}'")

        properties = schema.get("properties", {})
        properties = properties if isinstance(properties, dict) else {}
        allow_additional = bool(schema.get("additionalProperties", True))

        if not allow_additional:
            for key in value:
                if key not in properties:
                    raise AdapterExecutionError(
                        f"schema validation failed at {path}: unexpected field '{key}'"
                    )

        for key, child_schema in properties.items():
            if key not in value:
                continue
            if not isinstance(child_schema, dict):
                continue
            self._validate_node(value[key], child_schema, path=f"{path}.{key}")

    def _validate_array(self, value: list[object], schema: dict[str, object], path: str) -> None:
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            raise AdapterExecutionError(f"schema validation failed at {path}: invalid items schema")

        for index, entry in enumerate(value):
            self._validate_node(entry, item_schema, path=f"{path}[{index}]")

    def _parse_timestamp(self, timestamp_raw: str) -> float:
        normalized = timestamp_raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError as exc:
            raise AdapterExecutionError("schema validation failed: invalid timestamp") from exc


class TelemetryPerceptionPipeline(PerceptionPipeline):
    def __init__(
        self,
        telemetry_source: Callable[[], dict[str, object] | None],
        schema_validator: TelemetrySchemaValidator,
        tracker: DeterministicObstacleTracker | None = None,
    ) -> None:
        self.telemetry_source = telemetry_source
        self.schema_validator = schema_validator
        self.tracker = tracker or DeterministicObstacleTracker()

    def observe(self, state: VehicleState) -> PerceptionFrame:
        telemetry_event = self.telemetry_source()
        if telemetry_event is None:
            return PerceptionFrame(timestamp_s=time.time())

        self.schema_validator.validate(telemetry_event)

        timestamp = self._event_timestamp(telemetry_event)
        lidar = telemetry_event.get("lidar_obstacles", [])
        obstacles = self._parse_obstacles(lidar)
        tracked_obstacles = self.tracker.update(obstacles, timestamp)
        sensor_health = self._sensor_health(telemetry_event)
        return PerceptionFrame(
            timestamp_s=timestamp,
            obstacles=tracked_obstacles,
            sensor_health=sensor_health,
            telemetry=telemetry_event,
            tracking_summary=self._tracking_summary(tracked_obstacles),
        )

    def _event_timestamp(self, telemetry_event: dict[str, object]) -> float:
        timestamp_raw = telemetry_event.get("timestamp")
        if not isinstance(timestamp_raw, str):
            raise AdapterExecutionError("telemetry timestamp missing")
        normalized = timestamp_raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError as exc:
            raise AdapterExecutionError("telemetry timestamp invalid") from exc

    def _parse_obstacles(self, lidar: object) -> list[DetectedObstacle]:
        if not isinstance(lidar, list):
            return []

        obstacles: list[DetectedObstacle] = []
        for obstacle in lidar:
            if not isinstance(obstacle, dict):
                continue
            x = obstacle.get("x")
            y = obstacle.get("y")
            radius_m = obstacle.get("radius_m")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            if not isinstance(radius_m, (int, float)):
                continue

            confidence_raw = obstacle.get("confidence", 1.0)
            source_raw = obstacle.get("source", "lidar")
            confidence = self._normalize_confidence(confidence_raw)
            source = str(source_raw)
            object_id_raw = obstacle.get("object_id")
            class_label_raw = obstacle.get("class_label", "unknown")
            object_id = str(object_id_raw) if isinstance(object_id_raw, str) and object_id_raw else None
            class_label = str(class_label_raw)

            obstacles.append(
                DetectedObstacle(
                    x=float(x),
                    y=float(y),
                    radius_m=max(0.0, float(radius_m)),
                    confidence=confidence,
                    source=source,
                    track_id=object_id,
                    class_label=class_label,
                )
            )
        return obstacles

    def _normalize_confidence(self, confidence_raw: object) -> float:
        if not isinstance(confidence_raw, (int, float)):
            return 1.0

        value = float(confidence_raw)
        if value > 1.0 and value <= 100.0:
            value = value / 100.0
        return min(max(value, 0.0), 1.0)

    def _tracking_summary(self, obstacles: list[DetectedObstacle]) -> dict[str, int | float]:
        if not obstacles:
            return {"tracked_count": 0, "avg_confidence": 0.0}

        avg_confidence = sum(obstacle.confidence for obstacle in obstacles) / len(obstacles)
        return {
            "tracked_count": len(obstacles),
            "avg_confidence": avg_confidence,
        }

    def _sensor_health(self, telemetry_event: dict[str, object]) -> dict[str, bool]:
        return {
            "gps": "gps_x" in telemetry_event and "gps_y" in telemetry_event,
            "imu": "imu_vx_mps" in telemetry_event and "imu_vy_mps" in telemetry_event,
            "lidar": bool(telemetry_event.get("lidar_obstacles")),
        }
