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
