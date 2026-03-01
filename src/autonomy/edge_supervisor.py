import time
from dataclasses import replace

from .audit import SignedAuditLogger
from .controller import ActionPassthroughController, Controller
from .errors import AdapterExecutionError
from .localization import LocalizationEngine, PassThroughLocalizationEngine
from .mapping import GeofenceMappingService, MappingService
from .models import Action, ActionType, MissionPlan, VehicleState
from .obstacle_avoidance import AvoidancePlanner, PassThroughAvoidancePlanner
from .perception import NullPerceptionPipeline, PerceptionPipeline
from .reason_codes import to_policy_reason_code
from .safety_kernel import SafetyKernel
from .vehicle_adapter import VehicleAdapter


class EdgeSupervisor:
    def __init__(
        self,
        safety_kernel: SafetyKernel,
        adapter: VehicleAdapter,
        failover_adapter: VehicleAdapter | None = None,
        audit_logger: SignedAuditLogger | None = None,
        perception_pipeline: PerceptionPipeline | None = None,
        localization_engine: LocalizationEngine | None = None,
        mapping_service: MappingService | None = None,
        avoidance_planner: AvoidancePlanner | None = None,
        controller: Controller | None = None,
    ) -> None:
        self.safety_kernel = safety_kernel
        self.adapter = adapter
        self.failover_adapter = failover_adapter
        self.audit_logger = audit_logger
        self.perception_pipeline = perception_pipeline or NullPerceptionPipeline()
        self.localization_engine = localization_engine or PassThroughLocalizationEngine()
        self.mapping_service = mapping_service or GeofenceMappingService(
            geofence_abs_xy_limit_m=self.safety_kernel.config.geofence_abs_xy_limit_m
        )
        self.avoidance_planner = avoidance_planner or PassThroughAvoidancePlanner()
        self.controller = controller or ActionPassthroughController()

    def run_plan(self, initial_state: VehicleState, plan: MissionPlan) -> tuple[VehicleState, list[str]]:
        state = initial_state
        events: list[str] = []

        for action in plan.actions:
            try:
                perception_frame = self.perception_pipeline.observe(state)
                localization = self.localization_engine.estimate(state, perception_frame)
                if not localization.fresh:
                    raise AdapterExecutionError("localization_stale")

                sensor_age_s = max(0.0, time.time() - perception_frame.timestamp_s)
                nearest_obstacle_distance = self.mapping_service.nearest_obstacle_distance(
                    localization.x,
                    localization.y,
                    perception_frame,
                )
                state_for_checks = replace(
                    state,
                    x=localization.x,
                    y=localization.y,
                    heading_rad=localization.heading_rad,
                    vx_mps=localization.vx_mps,
                    vy_mps=localization.vy_mps,
                    position_std_m=localization.position_std_m,
                    sensor_age_s=sensor_age_s,
                    nearest_obstacle_distance_m=nearest_obstacle_distance,
                )

                action_for_execution = self.avoidance_planner.refine_action(
                    action,
                    localization,
                    perception_frame,
                    self.mapping_service,
                )
                control_command = self.controller.command_for_action(action_for_execution, localization)
                action_for_execution = control_command.action
            except AdapterExecutionError as exc:
                reason_detail = str(exc)
                events.append(self._policy_block_event(reason_detail))
                fallback = self.safety_kernel.fallback_action()
                state = self._execute_action(state, fallback, events)
                events.append(f"fallback:{fallback.type.value}")
                self._audit("policy_block", state, reason_detail)
                self._audit("fallback", state, fallback.type.value)
                break
            except Exception as exc:  # noqa: BLE001
                reason_detail = "subsystem_failure"
                events.append(self._policy_block_event(reason_detail))
                fallback = self.safety_kernel.fallback_action()
                state = self._execute_action(state, fallback, events)
                events.append(f"fallback:{fallback.type.value}")
                self._audit("policy_block", state, f"subsystem_failure:{exc}")
                self._audit("fallback", state, fallback.type.value)
                break

            if action_for_execution.type == ActionType.MOVE_TO and action_for_execution.speed_mps is not None:
                if action_for_execution.speed_mps > self.adapter.capability_profile.max_speed_mps:
                    reason_detail = "adapter_speed_limit"
                    events.append(self._policy_block_event(reason_detail))
                    fallback = self.safety_kernel.fallback_action()
                    state = self._execute_action(state, fallback, events)
                    events.append(f"fallback:{fallback.type.value}")
                    self._audit("policy_block", state, reason_detail)
                    self._audit("fallback", state, fallback.type.value)
                    break

            if not self.adapter.supports(action_for_execution):
                reason_detail = "adapter_capability_unsupported"
                events.append(self._policy_block_event(reason_detail))
                fallback = self.safety_kernel.fallback_action()
                state = self._execute_action(state, fallback, events)
                events.append(f"fallback:{fallback.type.value}")
                self._audit("policy_block", state, reason_detail)
                self._audit("fallback", state, fallback.type.value)
                break

            ok, reason = self.safety_kernel.precheck(state_for_checks, action_for_execution)
            if not ok:
                reason_detail = reason or "unknown"
                events.append(self._policy_block_event(reason_detail))
                fallback = self.safety_kernel.fallback_action()
                state = self._execute_action(state, fallback, events)
                events.append(f"fallback:{fallback.type.value}")
                self._audit("policy_block", state, reason_detail)
                self._audit("fallback", state, fallback.type.value)
                break

            try:
                state = self._execute_action(state, action_for_execution, events)
                events.append(f"exec:{action_for_execution.type.value}")
                self._audit("exec", state, action_for_execution.type.value)
            except AdapterExecutionError:
                reason_detail = "transport_failure"
                events.append(self._policy_block_event(reason_detail))
                fallback = self.safety_kernel.fallback_action()
                try:
                    state = self._execute_action(state, fallback, events)
                    events.append(f"fallback:{fallback.type.value}")
                    self._audit("policy_block", state, reason_detail)
                    self._audit("fallback", state, fallback.type.value)
                except AdapterExecutionError:
                    events.append("system_fault:fallback_transport_failure")
                break

        if state.battery_pct < 10 and state.armed:
            try:
                state = self._execute_action(state, self.safety_kernel.fallback_action(), events)
                events.append(f"fallback:{ActionType.RETURN_TO_HOME.value}")
                self._audit("fallback", state, ActionType.RETURN_TO_HOME.value)
            except AdapterExecutionError:
                events.append("system_fault:fallback_transport_failure")

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

    def _execute_action(self, state: VehicleState, action: Action, events: list[str]) -> VehicleState:
        try:
            return self.adapter.execute(state, action)
        except AdapterExecutionError as primary_error:
            if self.failover_adapter is None:
                raise
            recovered_state = self.failover_adapter.execute(state, action)
            events.append(f"failover_adapter_used:{action.type.value}")
            self._audit("failover", recovered_state, str(primary_error))
            return recovered_state

    def _policy_block_event(self, reason_detail: str) -> str:
        return f"policy_block:{to_policy_reason_code(reason_detail)}"
