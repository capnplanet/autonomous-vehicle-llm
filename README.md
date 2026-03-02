# Autonomy Stack (MVP Scaffold)

Safety-first scaffold for autonomous movement of unmanned vehicles.

## Executive Summary (Feynman-style)

Think of this repo as an autonomous operations team in software:

- **LLM planner** = the pilot that suggests mission steps.
- **Verifier + safety kernel** = the checklist and safety officer that can block unsafe or malformed actions.
- **Supervisor + adapters/transports** = the operations crew that actually executes commands and handles degraded conditions.
- **Audit + approvals + signed updates** = compliance and release governance that records who changed what, when, and why.

In short: the model can be smart, but it is never trusted alone. Deterministic controls make final execution decisions.

### Executive use cases

- **Drone field operations**: patrol/inspection planning with deterministic geofence/speed/battery guardrails.
- **Industrial IoT actuation**: policy-gated commands for pumps/valves/controllers with signed ACK validation.
- **Mixed-vendor autonomous fleets**: secure transport with idempotency, replay defense, key rotation, and cert pinning.
- **High-assurance rollout governance**: quorum-signed bundles, canary-to-global promotion, dual-control approvals, and tamper-evident logs.
- **Operational readiness benchmarking**: strict pass metrics that separate “mission completed” from “primary transport truly healthy.”

## What this repo is now capable of

- **Hosted LLM integration (Hugging Face)** without local model loading, including OpenAI-compatible endpoint fallback support.
- **End-to-end plan pipeline**: plan generation → verifier checks → safety-gated execution.
- **Strict benchmark modes** via CLI:
	- baseline planner/execution metrics,
	- no-failover local-primary runs,
	- strict transport-required runs.
- **Transport-layer assurance**: ACK correlation, nonce replay defense, Ed25519 signature verification, certificate pin attestation.
- **Resilience controls**: primary/secondary adapter behavior with explicit failover observability in metrics.
- **Update and approval governance**: signed update bundles, environment-scoped approvals, dual-control production canary approvals.
- **Tamper-evident audit chain**: append-only approval logs with sealing and fail-closed verification on startup/append.

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

### Benchmark planner + automation metrics

Run repeated planner → verifier → supervisor cycles and emit a JSON metrics report:

```bash
python -m src.main benchmark --runs 20 --goal "patrol sector alpha" --output logs/benchmark-llama.json
```

The benchmark reports planner error rate, verifier pass rate, execution success rate, latency stats (avg/p95/max), and per-run records.

To run with no failover path, disable failover and use local primary execution:

```bash
python -m src.main benchmark --runs 20 --goal "patrol sector alpha" --no-failover --local-primary --output logs/benchmark-no-failover.json
```

To enforce strict pass criteria and require primary transport success (no failover usage):

```bash
python -m src.main benchmark --runs 20 --goal "patrol sector alpha" --strict-pass --require-transport-success --output logs/benchmark-strict-transport.json
```

For a local end-to-end transport validation, run the mock vendor gateway in one terminal:

```bash
python scripts/mock_vendor_gateway.py
```

Then run strict transport benchmark in another terminal using the mock transport profile:

```bash
python -m src.main benchmark --runs 20 --goal "patrol sector alpha" --strict-pass --require-transport-success --transport-config config/transport.mock.json --output logs/benchmark-strict-transport.json
```

### Using a Hugging Face hosted LLM (no local weights)

To avoid slowing down this workspace, call Llama 3.1 8B via Hugging Face over HTTPS (Inference API or a dedicated Endpoint):

```bash
export HF_TOKEN="..."
export HF_MODEL_ID="meta-llama/Llama-3.1-8B-Instruct"  # or set HF_ENDPOINT_URL for a dedicated endpoint
python -m src.main demo
```

Notes:
- This keeps the model out-of-process (no `transformers` load in the dev container).
- For lower latency and fewer cold starts, prefer a dedicated Hugging Face Inference Endpoint and set `HF_ENDPOINT_URL`.
- Some dedicated endpoints expose only OpenAI-compatible routes; in that case the planner auto-falls back to `HF_ENDPOINT_URL/v1/chat/completions` and needs `HF_MODEL_ID` (or `HF_CHAT_MODEL`) set.

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

## Operations Guide

- LLM + transport benchmarking runbook: [docs/operations/llm-transport-benchmark-guide.md](docs/operations/llm-transport-benchmark-guide.md)
