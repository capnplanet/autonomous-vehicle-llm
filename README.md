# Autonomy Stack (MVP Scaffold)

Safety-first scaffold for autonomous movement of unmanned vehicles.

## Components

- `cloud_planner`: builds mission plans from goals.
- `plan_verifier`: validates plans against mission schema and static constraints.
- `safety_kernel`: deterministic policy checks and fail-safe decisions.
- `edge_supervisor`: executes approved plans through a vehicle adapter.
- `vehicle_adapter`: capability profiles for ground/aerial/marine adapters.
- `transport`: HTTP/MQTT command transport stubs with auth, timeout, and retry.
- `audit`: tamper-evident signed audit log chain.

## Quick Start

```bash
python -m src.main
```

## Config

- Policy file: `config/policy.default.json`
- Transport file: `config/transport.default.json`
- Audit log output: `logs/audit.log`

## Runtime Failover

- Primary path uses a transport-backed adapter.
- On transport failure, `edge_supervisor` can execute the same action via a failover adapter.

## Safety Principle

The LLM can propose plans, but deterministic policy gates must approve each action before execution.
