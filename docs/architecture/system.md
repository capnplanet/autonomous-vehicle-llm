# System Architecture

## Components

- `cloud_planner`: Generates mission plans from high-level goals.
- `plan_verifier`: Rejects malformed or unsafe-by-structure plans.
- `edge_supervisor`: Executes actions on edge with deterministic control loop.
- `safety_kernel`: Enforces policy constraints before every action.
- `vehicle_adapter`: Abstracts vendor-specific APIs for each vehicle type.

## Control Principle

LLM output is never directly executed. Every action must pass deterministic checks.

## Fallback

Primary fail-safe for MVP is `return_to_home` on policy violation or degraded state.
