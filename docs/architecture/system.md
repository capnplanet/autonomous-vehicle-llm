# System Architecture

## Components

- `cloud_planner`: Generates mission plans from high-level goals.
- `plan_verifier`: Rejects malformed or unsafe-by-structure plans.
- `edge_supervisor`: Executes actions on edge with deterministic control loop.
- `safety_kernel`: Enforces policy constraints before every action.
- `perception`: Produces obstacle/sensor frames from telemetry input.
- `localization`: Produces pose/velocity/uncertainty estimates.
- `mapping`: Resolves geofence and nearest-obstacle queries.
- `obstacle_avoidance`: Refines planned actions into locally safe actions.
- `controller`: Converts actions to control commands for execution.
- `replay`: Provides deterministic telemetry replay for repeatable closed-loop tests.
- `trace`: Produces scenario-level JSON execution trace artifacts.
- `vehicle_adapter`: Abstracts vendor-specific APIs for each vehicle type.

## Control Principle

LLM output is never directly executed. Every action must pass deterministic checks.

## Fallback

Primary fail-safe for MVP is `return_to_home` on policy violation or degraded state.
