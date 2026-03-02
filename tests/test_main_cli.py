from __future__ import annotations

import subprocess
import sys


def test_trace_list_scenarios_cli_outputs_names():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "trace", "--list-scenarios"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "nominal_replay" in result.stdout


def test_trace_cli_requires_scenario_or_list():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "trace"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "requires --scenario" in result.stderr


def test_trace_cli_runs_named_scenario(tmp_path):
    output = tmp_path / "cli-trace.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            "trace",
            "--scenario",
            "blocked_target",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert output.exists()
    assert "Trace artifact written:" in result.stdout


def test_benchmark_cli_runs_and_writes_output(tmp_path):
    output = tmp_path / "benchmark.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            "benchmark",
            "--runs",
            "2",
            "--goal",
            "patrol sector alpha",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert output.exists()
    assert "Benchmark artifact written:" in result.stdout


def test_benchmark_cli_requires_positive_runs():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "benchmark", "--runs", "0"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "requires --runs > 0" in result.stderr


def test_benchmark_cli_no_failover_local_primary(tmp_path):
    output = tmp_path / "benchmark-no-failover.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            "benchmark",
            "--runs",
            "2",
            "--goal",
            "patrol sector alpha",
            "--no-failover",
            "--local-primary",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert output.exists()


def test_benchmark_cli_transport_requirement_rejects_local_primary():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            "benchmark",
            "--runs",
            "1",
            "--local-primary",
            "--require-transport-success",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "requires transport primary mode" in result.stderr
