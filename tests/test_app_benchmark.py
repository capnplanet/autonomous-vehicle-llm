from __future__ import annotations

import json

from autonomy.app import run_benchmark


def test_run_benchmark_returns_summary_structure(tmp_path):
    output = tmp_path / "benchmark.json"

    summary, path = run_benchmark(runs=3, goal="patrol sector alpha", output_path=str(output))

    assert path == output
    assert summary["runs"] == 3
    assert summary["planner"] in {"stub", "huggingface"}
    assert isinstance(summary["records"], list)
    assert len(summary["records"]) == 3
    assert output.exists()

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["runs"] == 3
    assert "planning_latency_ms" in written
    assert "execution_latency_ms" in written


def test_run_benchmark_rates_are_bounded():
    summary, _ = run_benchmark(runs=2, goal="patrol sector alpha")

    assert 0.0 <= float(summary["planner_error_rate"]) <= 1.0
    assert 0.0 <= float(summary["verifier_pass_rate"]) <= 1.0
    assert 0.0 <= float(summary["execution_success_rate"]) <= 1.0
    assert 0.0 <= float(summary["strict_success_rate"]) <= 1.0


def test_run_benchmark_strict_pass_with_local_primary(tmp_path):
    summary, _ = run_benchmark(
        runs=2,
        goal="patrol sector alpha",
        output_path=str(tmp_path / "strict.json"),
        use_transport_primary=False,
        enable_failover=False,
        strict_pass=True,
    )

    assert summary["strict_success_count"] == 2
    for record in summary["records"]:
        assert record["strict_success"] is True


def test_run_benchmark_transport_requirement_needs_transport_primary():
    try:
        run_benchmark(
            runs=1,
            goal="patrol sector alpha",
            use_transport_primary=False,
            require_transport_success=True,
        )
    except ValueError as exc:
        assert "requires transport primary mode" in str(exc)
    else:
        raise AssertionError("expected ValueError")
