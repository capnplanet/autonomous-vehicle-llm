from __future__ import annotations

from abc import ABC, abstractmethod

from .localization import LocalizationEstimate
from .mapping import MappingService
from .models import Action
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
