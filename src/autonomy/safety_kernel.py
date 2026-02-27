from .models import Action, ActionType, PolicyConfig, VehicleState


class SafetyKernel:
    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def precheck(self, state: VehicleState, action: Action) -> tuple[bool, str | None]:
        if not state.connected:
            return False, "vehicle disconnected"

        if action.type == ActionType.MOVE_TO:
            if action.speed_mps is None or action.speed_mps > self.config.max_speed_mps:
                return False, "speed exceeds policy"
            if state.battery_pct < self.config.min_battery_for_motion_pct:
                return False, "battery below motion threshold"
            if action.x is None or action.y is None:
                return False, "missing move target"
            if abs(action.x) > self.config.geofence_abs_xy_limit_m:
                return False, "target x out of geofence"
            if abs(action.y) > self.config.geofence_abs_xy_limit_m:
                return False, "target y out of geofence"

        if action.type == ActionType.DISARM and (abs(state.x) > 0.01 or abs(state.y) > 0.01):
            return False, "cannot disarm away from home"

        return True, None

    def fallback_action(self) -> Action:
        return Action(type=ActionType.RETURN_TO_HOME)
