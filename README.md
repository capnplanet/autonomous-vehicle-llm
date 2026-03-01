# Autonomy Stack (MVP Scaffold)

Safety-first scaffold for autonomous movement of unmanned vehicles.

## Components

- `cloud_planner`: builds mission plans from goals.
- `plan_verifier`: validates plans against mission schema and static constraints.
- `safety_kernel`: deterministic policy checks and fail-safe decisions.
- `edge_supervisor`: executes approved plans through a vehicle adapter.
- `perception`: perception frame and obstacle signal pipeline interfaces.
- `localization`: localization estimate interfaces (pose/velocity/uncertainty).
- `mapping`: geofence and obstacle-distance query interfaces.
- `obstacle_avoidance`: local action refinement hooks.
- `controller`: action-to-command closed-loop control hooks.
- `replay`: deterministic telemetry replay source for repeatable simulation tests.
- `trace`: replay-driven mission trace runner with JSON artifact export.
- `vehicle_adapter`: capability profiles for ground/aerial/marine adapters.
- `transport`: vendor-integrated HTTP/MQTT transports with auth rotation, TLS/mTLS, ACK correlation, and idempotency keys.
- `ledger`: durable SQLite command ledger for idempotency persistence and per-vehicle ACK nonce tracking.
- `keyring`: per-vendor Ed25519 public keys with rotation and revocation support.
- `cert_pins`: per-vendor certificate fingerprint pinsets for mTLS identity attestation.
- `bundle_updater`: signed, versioned key/pin/rollout update bundles with tamper-evident chain state.
- `audit`: tamper-evident signed audit log chain.

## Quick Start

```bash
python -m src.main
```

## CLI

Run demo mission:

```bash
python -m src.main demo
```

List available replay trace scenarios:

```bash
python -m src.main trace --list-scenarios
```

Run a named trace scenario and write artifact under `logs/traces/` automatically:

```bash
python -m src.main trace --scenario nominal_replay
```

Run a named trace scenario with explicit output path:

```bash
python -m src.main trace --scenario blocked_target --output logs/traces/blocked-target.json
```

## Config

- Policy file: `config/policy.default.json`
- Transport file: `config/transport.default.json`
- Audit log output: `logs/audit.log`

Transport config supports rotating bearer tokens, TLS/mTLS cert paths, command ACK field mapping, nonce replay windows, Ed25519 signature verification, key-id/vendor routing, certificate fingerprint pinsets, and durable idempotency store paths.

Certificate pinsets support staged rollout via `active` and `next` windows, automatic cutover when active pins expire, and rollback to previous active pins.

Transport rollout policy supports automatic certificate pin rollback when ACK verification failure rate breaches configured thresholds.

Bundle updates support quorum signatures (`min_signatures` in trust policy) and canary-stage gating, where global activation requires explicit canary approval.

Approvals are environment-scoped (`dev`/`staging`/`prod`) with stricter quorum in higher environments; production global activation requires canary soak-time and error-rate metrics to satisfy trust policy thresholds.

Canary approvals are written to an append-only hash-chained audit log with HMAC-based record sealing, and production canary approval supports dual-control by requiring distinct approvers before global activation.

Approval audit integrity is periodically re-verified during writes (`approval_audit_verify_every_writes`) and can be verified on demand via the ledger verifier API.

Approval audit verification is fail-closed on startup and before append by default (`approval_audit_verify_before_append=true`), preventing new approvals from being logged if existing audit data has been tampered.

## Runtime Failover

- Primary path uses a transport-backed adapter.
- On transport failure, `edge_supervisor` can execute the same action via a failover adapter.

`edge_supervisor` now supports optional perception → localization → mapping → avoidance → controller hooks before action execution. Defaults are pass-through/no-op to preserve MVP behavior.

Phase 2 adds `TelemetryPerceptionPipeline` with schema validation against `specs/events/telemetry.schema.json`, plus `FusedTelemetryLocalizationEngine` for GPS/IMU-fused state estimates and freshness checks.

Perception now includes deterministic obstacle tracking (`track_id`, age, estimated obstacle velocity) and confidence normalization (`0..1` or `0..100` telemetry confidence inputs).

Phase 3 adds `ClearanceAwareAvoidancePlanner`, which reroutes blocked `move_to` targets to nearby safe candidates (or `hold` if no safe option), plus deterministic telemetry replay utilities for repeatable integration testing.

Phase 3 continuation adds `MissionTraceRunner` for scenario execution traces with verifier result, execution events, and replay consumption metrics written to JSON artifacts.

Trace artifacts now include `contract_version` and canonical `policy_reason_codes` to keep safety explanations deterministic and machine-checkable across upgrades.

## Safety Principle

The LLM can propose plans, but deterministic policy gates must approve each action before execution.
