# Hybrid Agent integration changes

## Current integration pass

- Added a pure simulation-only actuator command evaluator for freshness, dissolved-oxygen quality/safety, water-level availability, and simulated feedback fault profiles.
- Added `GET /api/v1/edge/actuator-simulation-profiles`.
- Added `POST /api/v1/edge/commands/{command_id}/simulate-result`; it can process a queued simulation command once and never calls a physical driver.
- Edge status now distinguishes API reachability from a connected edge gateway; no heartbeat is fabricated.
- Added Simulator & Diagnostics controls to simulate normal feedback, stuck actuator, and lost feedback outcomes.
- Added targeted tests for stale telemetry, unsafe aerator-off requests, missing water-level interlock data, and feedback mismatch.
- Added `docs/edge_actuator_simulation.md` with operator steps and physical commissioning boundary.

## Verification performed

- Targeted agent/edge tests: 10 passed.
- Python source compilation: passed.
- Dashboard JS and API JS syntax checks: passed.
- Live API/database/browser/hardware validation: not performed in this pass.

## Integrated UI/readiness update (2026-10-14)
- Replaced fixed-count/static overview category cards with authenticated, live System Readiness cards for agent capabilities, simulator state, edge connection and physical-actuation safety boundary.
- Added pond-level Operational History timeline for telemetry, decisions and DRY_RUN command records.
- Harmonized legacy dark inline panels with the common light UI, improved responsive readiness cards, and removed unverified transformer-to-pond labels and prefilled apparent FCR.
- Standardized fixed farm-economics and expense displays to INR while retaining explicitly selected currencies in cash-flow/budget forms.
- See `docs/INTEGRATED_RELEASE_UI_AND_READINESS.md` for verification and remaining commissioning requirements.
