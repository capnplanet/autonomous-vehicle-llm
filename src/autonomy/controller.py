from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .localization import LocalizationEstimate
from .models import Action


@dataclass(slots=True)
class ControlCommand:
    action: Action
    issued_at_s: float


class Controller(ABC):
    @abstractmethod
    def command_for_action(self, action: Action, localization: LocalizationEstimate) -> ControlCommand:
        raise NotImplementedError


class ActionPassthroughController(Controller):
    def command_for_action(self, action: Action, localization: LocalizationEstimate) -> ControlCommand:
        return ControlCommand(action=action, issued_at_s=time.time())
