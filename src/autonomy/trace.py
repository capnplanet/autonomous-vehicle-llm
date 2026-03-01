from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .edge_supervisor import EdgeSupervisor
from .models import MissionPlan, VehicleState
from .plan_verifier import PlanVerifier
from .reason_codes import extract_policy_reason_codes
from .replay import DeterministicTelemetryReplay


TRACE_CONTRACT_VERSION = "1.0"


@dataclass(slots=True)
class MissionTraceArtifact:
    contract_version: str
    scenario: str
    status: str
    started_at_s: float
    completed_at_s: float
    initial_state: dict[str, object]
    final_state: dict[str, object] | None
    plan: dict[str, object]
    events: list[str]
    policy_reason_codes: list[str]
    errors: list[str]
    telemetry_events_total: int | None
    telemetry_events_consumed: int | None


class MissionTraceRunner:
    def __init__(self, supervisor: EdgeSupervisor, verifier: PlanVerifier) -> None:
        self.supervisor = supervisor
        self.verifier = verifier

    def run(
        self,
        scenario: str,
        initial_state: VehicleState,
        plan: MissionPlan,
        replay: DeterministicTelemetryReplay | None = None,
        output_path: str | Path | None = None,
    ) -> MissionTraceArtifact:
        started = time.time()
        ok, errors = self.verifier.verify(plan)
        if not ok:
            completed = time.time()
            artifact = MissionTraceArtifact(
                contract_version=TRACE_CONTRACT_VERSION,
                scenario=scenario,
                status="rejected",
                started_at_s=started,
                completed_at_s=completed,
                initial_state=asdict(initial_state),
                final_state=None,
                plan=asdict(plan),
                events=[],
                policy_reason_codes=[],
                errors=errors,
                telemetry_events_total=replay.total() if replay else None,
                telemetry_events_consumed=replay.consumed() if replay else None,
            )
            if output_path is not None:
                self._write(output_path, artifact)
            return artifact

        final_state, events = self.supervisor.run_plan(initial_state, plan)
        completed = time.time()
        artifact = MissionTraceArtifact(
            contract_version=TRACE_CONTRACT_VERSION,
            scenario=scenario,
            status="executed",
            started_at_s=started,
            completed_at_s=completed,
            initial_state=asdict(initial_state),
            final_state=asdict(final_state),
            plan=asdict(plan),
            events=events,
            policy_reason_codes=extract_policy_reason_codes(events),
            errors=[],
            telemetry_events_total=replay.total() if replay else None,
            telemetry_events_consumed=replay.consumed() if replay else None,
        )
        if output_path is not None:
            self._write(output_path, artifact)
        return artifact

    def _write(self, output_path: str | Path, artifact: MissionTraceArtifact) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(artifact), indent=2), encoding="utf-8")
