from __future__ import annotations

import argparse
import json
import sys

from src.autonomy.app import list_trace_scenarios, run_demo, run_trace_scenario


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomy stack CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("demo", help="Run demo mission")

    trace_parser = subparsers.add_parser("trace", help="Run named replay trace scenario")
    trace_parser.add_argument("--scenario", type=str, help="Scenario name to execute")
    trace_parser.add_argument("--output", type=str, help="Optional trace artifact output path")
    trace_parser.add_argument("--list-scenarios", action="store_true", help="List available scenario names")

    return parser


def _run_cli(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in {None, "demo"}:
        run_demo()
        return 0

    if args.command == "trace":
        if args.list_scenarios:
            for name in list_trace_scenarios():
                print(name)
            return 0

        if not args.scenario:
            parser.error("trace requires --scenario (or --list-scenarios)")

        try:
            artifact, output_path = run_trace_scenario(scenario_name=args.scenario, output_path=args.output)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        print(f"Trace artifact written: {output_path}")
        print(json.dumps({"scenario": artifact.scenario, "status": artifact.status}, separators=(",", ":")))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_run_cli(sys.argv[1:]))
