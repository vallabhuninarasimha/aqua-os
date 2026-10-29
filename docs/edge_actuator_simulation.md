# Aqua OS edge actuator simulation (DRY_RUN only)

## Purpose

This workflow validates command authorization, telemetry freshness, deterministic software interlocks, and actuator-feedback fault handling without connecting to or controlling physical equipment.

**This is not a physical commissioning procedure.** Every result produced by this simulator has `simulation_only: true`, `physical_command_sent: false`, and `physical_state_confirmed: false`. A simulated feedback match is not proof that a real motor, pump, contactor, valve, or aerator changed state.

## Available feedback profiles

- `NORMAL_FEEDBACK`: simulated feedback matches the requested state.
- `ACTUATOR_STUCK`: simulated feedback disagrees with the requested state.
- `FEEDBACK_LOST`: simulated feedback is unknown.

## UI workflow

1. Sign in with a user who has telemetry-write and advisory-ack permissions.
2. Open **Simulator & Diagnostics**.
3. Select a pond and apply a synthetic sensor dataset. The stream is explicitly marked simulated.
4. Create an advisory from the Farm AI Agent and approve it for the same farm and pond.
5. Enter the approved decision UUID and a registered actuator ID, then click **Record DRY_RUN command**.
6. Select a feedback profile and click **Simulate interlock & feedback**.
7. Inspect the command result. The result must state that no physical command was sent and no physical state was confirmed.

A new command is required to test another feedback profile because a command result can only be simulated once.

## API workflow

- `GET /api/v1/edge/actuator-simulation-profiles`
- `POST /api/v1/edge/commands` — records a command envelope in DRY_RUN mode.
- `POST /api/v1/edge/commands/{command_id}/simulate-result` — evaluates synthetic interlocks and feedback.
- `GET /api/v1/edge/commands` — inspects the recorded audit trail.

Example simulation request:

```json
{
  "farm_id": "farm-alpha",
  "feedback_profile": "ACTUATOR_STUCK",
  "max_telemetry_age_seconds": 120
}
```

The simulation requires fresh telemetry. Aerator OFF requests are blocked unless dissolved oxygen is present with `GOOD` quality and the current safety evaluation is safe. Water-pump ON requests are blocked unless water-level telemetry is present with `GOOD` quality. These are software-test guardrails, not a substitute for field-engineered electrical, hydraulic, or biological interlocks.

## Before any physical connection

Do not enable physical execution until all of the following are independently verified and documented: sensor calibration and units; correct pond/actuator mapping; electrical ratings and protection; independent emergency stop; hardwired interlocks; manual override; verified contactor/current feedback; fail-safe behavior on network/process/power loss; and site-approved operating limits. This code intentionally does not expose a physical-enable flag or a physical driver through the API.
