# Safety Case (MVP)

## Scope

Autonomous movement of unmanned vehicles across mixed domains.

## Top Hazards

1. Out-of-geofence movement.
2. Movement with low battery.
3. Unsafe speed command.
4. Disarm away from safe home location.

## Safety Requirements

- Deny movement beyond geofence limits.
- Deny movement below minimum battery threshold.
- Deny speed above policy max.
- On policy violation, trigger return-to-home.

## Evidence Sources

- Unit tests for policy checks.
- Simulation traces for nominal and blocked missions.
- Immutable execution event logs.
