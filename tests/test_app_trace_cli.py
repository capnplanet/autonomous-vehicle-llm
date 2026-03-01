from __future__ import annotations

import json

from autonomy.app import list_trace_scenarios, run_trace_scenario


def test_list_trace_scenarios_contains_expected_names():
    names = list_trace_scenarios()

    assert "nominal_replay" in names
    assert "blocked_target" in names


def test_run_trace_scenario_writes_artifact(tmp_path):
    output = tmp_path / "scenario-trace.json"

    artifact, path = run_trace_scenario("nominal_replay", output_path=str(output))

    assert path == output
    assert artifact.status == "executed"
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["scenario"] == "nominal_replay"
    assert written["status"] == "executed"


def test_run_trace_scenario_rejects_unknown_name():
    try:
        run_trace_scenario("not-a-real-scenario")
    except ValueError as exc:
        assert "unknown scenario" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown scenario")
