# LLM + Automation Framework Benchmark Guide

## Purpose

This document explains how to evaluate the Hugging Face–backed Llama planner inside this autonomy framework, how to read the benchmark outputs, and what the latest strict transport results mean.

## System Mental Model (Feynman-style)

Think of the stack as a flight team:

- **LLM planner** = trainee pilot (proposes the mission steps)
- **Plan verifier** = checklist officer (rejects malformed/unsafe plans)
- **Safety kernel + supervisor** = safety officer (enforces deterministic guardrails)
- **Primary transport** = radio link to real field equipment
- **Failover adapter** = backup co-pilot

A run is only a **strict pass** if the trainee, checklist, and radio all work with no need for backup.

## Benchmark Modes

### 1) Local primary, no failover

- Command path is simulator-only.
- Good for isolating planner/verifier/supervisor behavior.
- Does **not** prove transport-layer reliability.

Example:

```bash
python -m src.main benchmark \
  --runs 20 \
  --goal "patrol sector alpha" \
  --no-failover \
  --local-primary \
  --output logs/benchmark-no-failover.json
```

### 2) Strict transport benchmark (recommended for transport validation)

- Uses transport as primary execution path.
- Requires strict pass criteria.
- Requires transport success (no failover usage allowed for strict success).

Example:

```bash
python -m src.main benchmark \
  --runs 20 \
  --goal "patrol sector alpha" \
  --strict-pass \
  --require-transport-success \
  --transport-config config/transport.mock.json \
  --output logs/benchmark-strict-transport.json
```

## Mock Gateway Setup for End-to-End Transport Validation

Start mock gateway in one terminal:

```bash
python scripts/mock_vendor_gateway.py
```

Then run strict benchmark in another terminal (with HF vars set):

```bash
export HF_TOKEN="hf_..."
export HF_ENDPOINT_URL="https://<your-endpoint>"
export HF_MODEL_ID="meta-llama/Llama-3.1-8B-Instruct"

python -m src.main benchmark \
  --runs 10 \
  --goal "patrol sector alpha" \
  --strict-pass \
  --require-transport-success \
  --transport-config config/transport.mock.json \
  --output logs/benchmark-strict-transport.json
```

## What Each Metric Means

From benchmark output JSON:

- `planner_error_rate`: fraction of runs where planner call failed
- `verifier_pass_rate`: fraction of runs where plan passed structural/safety pre-checks
- `execution_success_rate`: runs that completed without system fault and with connected final state
- `strict_success_rate`: runs satisfying stricter criteria:
  - verifier passed
  - no policy blocks
  - no system faults
  - all plan actions executed
  - connected final state
  - if transport-required: no failover usage (`transport_primary_ok = true`)

Latency fields:

- `planning_latency_ms`: LLM planning time (dominant contributor)
- `execution_latency_ms`: action execution time in supervisor/adapter path

Per-run reliability fields:

- `failover_use_count`: how often fallback adapter was needed
- `policy_block_count`: deterministic safety/kernel blocks
- `system_fault_count`: hard execution faults
- `transport_primary_ok`: whether primary transport handled execution without failover

## Latest Interpreted Result (strict transport run)

Latest post-push strict transport benchmark (10 runs):

- planner error rate: **0.0**
- verifier pass rate: **1.0**
- execution success rate: **1.0**
- strict success rate: **0.9**

Interpretation:

- The planner and verifier are stable.
- All missions completed, but one run used failover.
- Operational success is high, but strict transport purity is not yet perfect (90%).

## How to Decide Go/No-Go

For field gating, use these minimum checks:

1. `planner_error_rate` near 0
2. `verifier_pass_rate` near 1
3. `strict_success_rate` at or above target SLO (example: 0.99)
4. `failover_use_count` trend near 0 for transport-required runs
5. p95 latency within mission timing budget

## Troubleshooting

- `404 Not Found` from HF endpoint:
  - Endpoint may be OpenAI-compatible only; ensure `HF_MODEL_ID` is set.
- `strict_success_rate` low with `execution_success_rate` high:
  - System is completing runs via failover; investigate primary transport reliability.
- Planner errors saying model missing:
  - Check `HF_MODEL_ID` and endpoint compatibility.

## Related Files

- Planner integration: `src/autonomy/hf_planner.py`
- Benchmark runner: `src/autonomy/app.py`
- CLI options: `src/main.py`
- Mock transport profile: `config/transport.mock.json`
- Mock gateway: `scripts/mock_vendor_gateway.py`
