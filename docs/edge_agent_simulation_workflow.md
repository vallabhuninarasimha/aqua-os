# Aqua OS decision-to-edge simulation workflow

## What this milestone adds

- Decision records expose a source `linked_action_id` and a conservative `correlation_key`.
- Creating a duplicate unresolved recommendation for the same farm/pond/category/title correlates it to the existing open decision rather than adding another active inbox row.
- `POST /api/v1/agent/decisions/{decision_id}/verify-telemetry` checks for telemetry newer than the last decision update and reports freshness, timestamp, simulated-source flag, and the existing safety evaluation. It intentionally returns `resolved: null`: a fresh reading is not proof that an action caused a condition to improve.
- `GET /api/v1/edge/ponds/{pond_id}/operational-history?farm_id=farm-alpha` merges decision history, DRY_RUN command records, and telemetry history. Synthetic readings retain `is_simulated=true`.
- The local edge command interface accepts only an approved decision for the same farm and pond and a registered actuator. It writes an auditable command envelope with `mode=DRY_RUN`; it never writes the aerator/pump desired or physical state and never calls a hardware driver.
- Sample scenario profiles are listed at `GET /api/v1/simulator/datasets` and can be applied at `POST /api/v1/simulator/datasets/{dataset_id}/apply`.

## Sample real-time sensor simulation

1. Authenticate to the API and select the intended farm/pond.
2. `GET /api/v1/simulator/datasets` to inspect the synthetic profiles.
3. `POST /api/v1/simulator/datasets/low-do-event/apply` with `{"farm_id":"farm-alpha","pond_id":"pond-01","duration_hours":0.5,"start_stream":true,"interval_seconds":3}`.
4. The existing in-process simulator writes generated telemetry with `is_simulated=true`. The current embedded simulator is configured only for the default farm and has a 20-pond generator; the endpoint rejects other farms rather than implying multi-farm simulation support.
5. Review telemetry and actions, create/review a decision, and use `verify-telemetry` to check that a newer reading exists.
6. Queue a dry-run command only after an operator decision is `APPROVED`, using a registered actuator ID. Inspect `GET /api/v1/edge/commands?farm_id=farm-alpha&pond_id=pond-01` and pond operational history.
7. Stop the simulator using the existing `POST /api/v1/simulator/stop` endpoint when finished. The assistant does not start or stop it for you.

## Sample dataset catalogue

`data/simulation_datasets/aqua_os_sensor_scenarios.json` defines baseline, sudden hypoxia, stale reading, aerator failure, and probe fouling test scenarios. These are synthetic scenario profiles, not prerecorded sensor measurements and not validated farm operating thresholds.

## Physical-control boundary

`GET /api/v1/edge/status` reports `SIMULATION_ONLY`. All queued commands have `physical_execution_enabled=false`, `physical_command_sent=false`, and are audit records only. Do not enable physical actuation until an independent emergency stop, hardwired interlocks, manual override, verified feedback, motor/transformer assignments, calibrated sensors, farm-approved limits, and commissioning sign-off are confirmed by qualified personnel.
