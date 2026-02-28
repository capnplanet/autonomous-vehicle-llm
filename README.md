# Autonomy Stack (MVP Scaffold)

Safety-first scaffold for autonomous movement of unmanned vehicles.

## Components

- `cloud_planner`: builds mission plans from goals.
- `plan_verifier`: validates plans against mission schema and static constraints.
- `safety_kernel`: deterministic policy checks and fail-safe decisions.
- `edge_supervisor`: executes approved plans through a vehicle adapter.
- `vehicle_adapter`: capability profiles for ground/aerial/marine adapters.
- `transport`: vendor-integrated HTTP/MQTT transports with auth rotation, TLS/mTLS, ACK correlation, and idempotency keys.
- `ledger`: durable SQLite command ledger for idempotency persistence and per-vehicle ACK nonce tracking.
- `keyring`: per-vendor Ed25519 public keys with rotation and revocation support.
- `cert_pins`: per-vendor certificate fingerprint pinsets for mTLS identity attestation.
- `audit`: tamper-evident signed audit log chain.

## Quick Start

```bash
python -m src.main
```

## Config

- Policy file: `config/policy.default.json`
- Transport file: `config/transport.default.json`
- Audit log output: `logs/audit.log`

Transport config supports rotating bearer tokens, TLS/mTLS cert paths, command ACK field mapping, nonce replay windows, Ed25519 signature verification, key-id/vendor routing, certificate fingerprint pinsets, and durable idempotency store paths.

Certificate pinsets support staged rollout via `active` and `next` windows, automatic cutover when active pins expire, and rollback to previous active pins.

## Runtime Failover

- Primary path uses a transport-backed adapter.
- On transport failure, `edge_supervisor` can execute the same action via a failover adapter.

## Safety Principle

The LLM can propose plans, but deterministic policy gates must approve each action before execution.
