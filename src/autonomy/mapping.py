from __future__ import annotations

import math
from abc import ABC, abstractmethod

from .perception import PerceptionFrame


class MappingService(ABC):
    @abstractmethod
    def is_within_geofence(self, x: float, y: float) -> bool:
        raise NotImplementedError

    @abstractmethod
    def nearest_obstacle_distance(self, x: float, y: float, frame: PerceptionFrame | None) -> float | None:
        raise NotImplementedError


class GeofenceMappingService(MappingService):
    def __init__(self, geofence_abs_xy_limit_m: float = 100.0) -> None:
        self.geofence_abs_xy_limit_m = geofence_abs_xy_limit_m

    def is_within_geofence(self, x: float, y: float) -> bool:
        return abs(x) <= self.geofence_abs_xy_limit_m and abs(y) <= self.geofence_abs_xy_limit_m

    def nearest_obstacle_distance(self, x: float, y: float, frame: PerceptionFrame | None) -> float | None:
        if frame is None or not frame.obstacles:
            return None

        nearest = min(
            (
                math.dist((x, y), (obstacle.x, obstacle.y)) - max(obstacle.radius_m, 0.0)
                for obstacle in frame.obstacles
            ),
            default=None,
        )
        return nearest
