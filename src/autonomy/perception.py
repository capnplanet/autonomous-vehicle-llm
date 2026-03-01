from __future__ import annotations

import json
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


@dataclass(slots=True)
class PerceptionFrame:
    timestamp_s: float
    obstacles: list[DetectedObstacle] = field(default_factory=list)
    sensor_health: dict[str, bool] = field(default_factory=dict)
    telemetry: dict[str, object] = field(default_factory=dict)


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
    ) -> None:
        self.telemetry_source = telemetry_source
        self.schema_validator = schema_validator

    def observe(self, state: VehicleState) -> PerceptionFrame:
        telemetry_event = self.telemetry_source()
        if telemetry_event is None:
            return PerceptionFrame(timestamp_s=time.time())

        self.schema_validator.validate(telemetry_event)

        timestamp = self._event_timestamp(telemetry_event)
        lidar = telemetry_event.get("lidar_obstacles", [])
        obstacles = self._parse_obstacles(lidar)
        sensor_health = self._sensor_health(telemetry_event)
        return PerceptionFrame(
            timestamp_s=timestamp,
            obstacles=obstacles,
            sensor_health=sensor_health,
            telemetry=telemetry_event,
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
            confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 1.0
            source = str(source_raw)

            obstacles.append(
                DetectedObstacle(
                    x=float(x),
                    y=float(y),
                    radius_m=max(0.0, float(radius_m)),
                    confidence=min(max(confidence, 0.0), 1.0),
                    source=source,
                )
            )
        return obstacles

    def _sensor_health(self, telemetry_event: dict[str, object]) -> dict[str, bool]:
        return {
            "gps": "gps_x" in telemetry_event and "gps_y" in telemetry_event,
            "imu": "imu_vx_mps" in telemetry_event and "imu_vy_mps" in telemetry_event,
            "lidar": bool(telemetry_event.get("lidar_obstacles")),
        }
