from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace

from .localization import LocalizationEstimate
from .mapping import MappingService
from .models import Action, ActionType
from .perception import PerceptionFrame


class AvoidancePlanner(ABC):
    @abstractmethod
    def refine_action(
        self,
        action: Action,
        localization: LocalizationEstimate,
        frame: PerceptionFrame | None,
        mapping_service: MappingService | None,
    ) -> Action:
        raise NotImplementedError


class PassThroughAvoidancePlanner(AvoidancePlanner):
    def refine_action(
        self,
        action: Action,
        localization: LocalizationEstimate,
        frame: PerceptionFrame | None,
        mapping_service: MappingService | None,
    ) -> Action:
        return action


class ClearanceAwareAvoidancePlanner(AvoidancePlanner):
    def __init__(self, min_clearance_m: float = 2.0, sidestep_m: float = 3.0) -> None:
        self.min_clearance_m = max(0.0, min_clearance_m)
        self.sidestep_m = max(0.0, sidestep_m)

    def refine_action(
        self,
        action: Action,
        localization: LocalizationEstimate,
        frame: PerceptionFrame | None,
        mapping_service: MappingService | None,
    ) -> Action:
        if action.type != ActionType.MOVE_TO:
            return action
        if action.x is None or action.y is None:
            return action
        if mapping_service is None:
            return action

        target_distance = mapping_service.nearest_obstacle_distance(action.x, action.y, frame)
        if target_distance is None or target_distance >= self.min_clearance_m:
            return action

        for delta_x, delta_y in self._candidate_offsets():
            candidate_x = action.x + delta_x
            candidate_y = action.y + delta_y
            if not mapping_service.is_within_geofence(candidate_x, candidate_y):
                continue
            candidate_distance = mapping_service.nearest_obstacle_distance(candidate_x, candidate_y, frame)
            if candidate_distance is None or candidate_distance >= self.min_clearance_m:
                return replace(action, x=candidate_x, y=candidate_y)

        return Action(type=ActionType.HOLD)

    def _candidate_offsets(self) -> list[tuple[float, float]]:
        step = self.sidestep_m
        return [
            (0.0, step),
            (0.0, -step),
            (step, 0.0),
            (-step, 0.0),
            (step, step),
            (step, -step),
            (-step, step),
            (-step, -step),
        ]
