from .audit import SignedAuditLogger
from .models import ActionType, MissionPlan, VehicleState
from .safety_kernel import SafetyKernel
from .vehicle_adapter import VehicleAdapter


class EdgeSupervisor:
    def __init__(
        self,
        safety_kernel: SafetyKernel,
        adapter: VehicleAdapter,
        audit_logger: SignedAuditLogger | None = None,
    ) -> None:
        self.safety_kernel = safety_kernel
        self.adapter = adapter
        self.audit_logger = audit_logger

    def run_plan(self, initial_state: VehicleState, plan: MissionPlan) -> tuple[VehicleState, list[str]]:
        state = initial_state
        events: list[str] = []

        for action in plan.actions:
            if action.type == ActionType.MOVE_TO and action.speed_mps is not None:
                if action.speed_mps > self.adapter.capability_profile.max_speed_mps:
                    events.append("policy_block:adapter_speed_limit")
                    fallback = self.safety_kernel.fallback_action()
                    state = self.adapter.execute(state, fallback)
                    events.append(f"fallback:{fallback.type.value}")
                    self._audit("policy_block", state, "adapter_speed_limit")
                    self._audit("fallback", state, fallback.type.value)
                    break

            if not self.adapter.supports(action):
                events.append("policy_block:adapter_capability_unsupported")
                fallback = self.safety_kernel.fallback_action()
                state = self.adapter.execute(state, fallback)
                events.append(f"fallback:{fallback.type.value}")
                self._audit("policy_block", state, "adapter_capability_unsupported")
                self._audit("fallback", state, fallback.type.value)
                break

            ok, reason = self.safety_kernel.precheck(state, action)
            if not ok:
                events.append(f"policy_block:{reason}")
                fallback = self.safety_kernel.fallback_action()
                state = self.adapter.execute(state, fallback)
                events.append(f"fallback:{fallback.type.value}")
                self._audit("policy_block", state, reason or "unknown")
                self._audit("fallback", state, fallback.type.value)
                break

            state = self.adapter.execute(state, action)
            events.append(f"exec:{action.type.value}")
            self._audit("exec", state, action.type.value)

        if state.battery_pct < 10 and state.armed:
            state = self.adapter.execute(state, self.safety_kernel.fallback_action())
            events.append(f"fallback:{ActionType.RETURN_TO_HOME.value}")
            self._audit("fallback", state, ActionType.RETURN_TO_HOME.value)

        return state, events

    def _audit(self, event_type: str, state: VehicleState, detail: str) -> None:
        if not self.audit_logger:
            return
        self.audit_logger.log(
            event_type=event_type,
            payload={
                "vehicle_id": state.vehicle_id,
                "x": state.x,
                "y": state.y,
                "battery_pct": state.battery_pct,
                "armed": state.armed,
                "detail": detail,
            },
        )
