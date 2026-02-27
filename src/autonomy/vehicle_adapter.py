from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace

from .models import Action, ActionType, CapabilityProfile, VehicleDomain, VehicleState


class VehicleAdapter(ABC):
    @property
    @abstractmethod
    def capability_profile(self) -> CapabilityProfile:
        raise NotImplementedError

    @abstractmethod
    def execute(self, state: VehicleState, action: Action) -> VehicleState:
        raise NotImplementedError

    def supports(self, action: Action) -> bool:
        if action.type == ActionType.RETURN_TO_HOME:
            return self.capability_profile.supports_return_to_home
        return True


class SimVehicleAdapter(VehicleAdapter):
    def __init__(self, capability_profile: CapabilityProfile | None = None) -> None:
        self._capability_profile = capability_profile or CapabilityProfile(
            domain=VehicleDomain.GROUND,
            max_speed_mps=8.0,
            supports_return_to_home=True,
        )

    @property
    def capability_profile(self) -> CapabilityProfile:
        return self._capability_profile

    def execute(self, state: VehicleState, action: Action) -> VehicleState:
        battery_drop = 0.2

        if action.type == ActionType.ARM:
            return replace(state, armed=True)

        if action.type == ActionType.MOVE_TO:
            if action.x is None or action.y is None:
                return state
            return replace(
                state,
                x=action.x,
                y=action.y,
                battery_pct=max(0.0, state.battery_pct - battery_drop),
            )

        if action.type == ActionType.HOLD:
            return replace(state, battery_pct=max(0.0, state.battery_pct - 0.05))

        if action.type == ActionType.RETURN_TO_HOME:
            return replace(
                state,
                x=state.home_x,
                y=state.home_y,
                battery_pct=max(0.0, state.battery_pct - battery_drop),
            )

        if action.type == ActionType.DISARM:
            return replace(state, armed=False)

        return state


class GroundVehicleAdapter(SimVehicleAdapter):
    def __init__(self) -> None:
        super().__init__(
            capability_profile=CapabilityProfile(
                domain=VehicleDomain.GROUND,
                max_speed_mps=7.0,
                supports_return_to_home=True,
            )
        )


class AerialVehicleAdapter(SimVehicleAdapter):
    def __init__(self) -> None:
        super().__init__(
            capability_profile=CapabilityProfile(
                domain=VehicleDomain.AERIAL,
                max_speed_mps=15.0,
                supports_return_to_home=True,
            )
        )


class MarineVehicleAdapter(SimVehicleAdapter):
    def __init__(self) -> None:
        super().__init__(
            capability_profile=CapabilityProfile(
                domain=VehicleDomain.MARINE,
                max_speed_mps=5.0,
                supports_return_to_home=True,
            )
        )
