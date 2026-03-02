from __future__ import annotations

import argparse
import json
import sys

from src.autonomy.app import list_trace_scenarios, run_benchmark, run_demo_with_options, run_trace_scenario


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomy stack CLI")
    subparsers = parser.add_subparsers(dest="command")

    demo_parser = subparsers.add_parser("demo", help="Run demo mission")
    demo_parser.add_argument(
        "--no-failover",
        action="store_true",
        help="Disable failover adapter execution",
    )
    demo_parser.add_argument(
        "--local-primary",
        action="store_true",
        help="Use local simulator adapter as primary (no transport)",
    )
    demo_parser.add_argument(
        "--transport-config",
        type=str,
        default="config/transport.default.json",
        help="Transport config file path used when transport primary mode is enabled",
    )

    trace_parser = subparsers.add_parser("trace", help="Run named replay trace scenario")
    trace_parser.add_argument("--scenario", type=str, help="Scenario name to execute")
    trace_parser.add_argument("--output", type=str, help="Optional trace artifact output path")
    trace_parser.add_argument("--list-scenarios", action="store_true", help="List available scenario names")

    benchmark_parser = subparsers.add_parser("benchmark", help="Run repeated planner benchmark and emit metrics")
    benchmark_parser.add_argument("--runs", type=int, default=10, help="Number of benchmark runs")
    benchmark_parser.add_argument("--goal", type=str, default="patrol sector alpha", help="Goal prompt for planner")
    benchmark_parser.add_argument("--output", type=str, help="Optional benchmark JSON output path")
    benchmark_parser.add_argument(
        "--no-failover",
        action="store_true",
        help="Disable failover adapter execution",
    )
    benchmark_parser.add_argument(
        "--local-primary",
        action="store_true",
        help="Use local simulator adapter as primary (no transport)",
    )
    benchmark_parser.add_argument(
        "--strict-pass",
        action="store_true",
        help="Count success only when all strict criteria are satisfied",
    )
    benchmark_parser.add_argument(
        "--require-transport-success",
        action="store_true",
        help="Require primary transport execution (no failover use) in success criteria",
    )
    benchmark_parser.add_argument(
        "--transport-config",
        type=str,
        default="config/transport.default.json",
        help="Transport config file path used when transport primary mode is enabled",
    )

    return parser


def _run_cli(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in {None, "demo"}:
        run_demo_with_options(
            use_transport_primary=not bool(getattr(args, "local_primary", False)),
            enable_failover=not bool(getattr(args, "no_failover", False)),
            transport_config_path=str(getattr(args, "transport_config", "config/transport.default.json")),
        )
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

    if args.command == "benchmark":
        if args.runs <= 0:
            parser.error("benchmark requires --runs > 0")

        try:
            summary, output_path = run_benchmark(
                runs=args.runs,
                goal=args.goal,
                output_path=args.output,
                use_transport_primary=not args.local_primary,
                enable_failover=not args.no_failover,
                strict_pass=args.strict_pass,
                require_transport_success=args.require_transport_success,
                transport_config_path=args.transport_config,
            )
        except ValueError as exc:
            parser.error(str(exc))
        if output_path is not None:
            print(f"Benchmark artifact written: {output_path}")
        print(json.dumps(summary, separators=(",", ":")))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_run_cli(sys.argv[1:]))
