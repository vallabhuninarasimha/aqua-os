# Aqua OS — Integrated UI and Readiness Update

## Changes included in this update

### Farm overview UI
- Replaced static category cards that claimed fixed counts or statuses with a System Readiness panel populated from authenticated agent, simulator, and edge-status API responses.
- Readiness cards show `AVAILABLE`, `UNAVAILABLE`, `IDLE`, `SIMULATING`, `NOT_CONNECTED`, or `UNVERIFIED` according to the returned response. An unknown or unavailable status is not presented as healthy.
- The overview explicitly states that physical actuation remains disabled and the edge controller has not been commissioned.
- Normalized the remaining inline dark panels to the common light Aqua OS theme, improved card hierarchy, spacing, borders, focus states, and mobile layout.
- Removed static transformer-to-pond group labels; the UI now indicates that assignments come from configuration.
- Removed the initial hardcoded apparent FCR value so it does not appear before a real response populates it.

### Pond operational history UI
- Added an Operational History tab to the pond detail modal.
- The tab calls the farm-scoped `GET /api/v1/edge/ponds/{pond_id}/operational-history` endpoint.
- Timeline records show telemetry, decisions and DRY_RUN commands in timestamp order, with simulated/physical-source provenance and an explicit warning that a requested command state is not physical confirmation.
- Added loading, empty and API-error states.

### Finance presentation
- Standardized farm financial labels and displays to INR for the farm economics/expense/inventory screens where the UI had previously shown USD symbols despite the INR accounting context.
- The general cash-flow/budget currency selector still supports INR and USD and uses the selected currency.

### Tests and documentation
- Updated the static dashboard test to assert the current Farm Operations Overview and System Readiness labels instead of the obsolete `20-Pond Baseline Live Monitor` title.
- Added this implementation and readiness note.

## Checks run

- `node --check apps/dashboard/js/dashboard.js` — passed.
- `node --check apps/dashboard/js/api.js` — passed.
- `python -m compileall -q apps/api/src` — passed.
- HTML ID and navigation-target static check — no duplicate IDs and no missing `data-target` targets.
- Targeted pytest selection (`tests/test_edge_agent_milestone.py`, `tests/test_agent_decision_engine.py`, `tests/test_dashboard_api.py`) — 16 passed.

## Not claimed as complete

- Browser rendering, responsive interaction and authenticated end-to-end API behavior were not exercised in a real browser.
- No physical sensor, PLC, Modbus device, motor, pump or aerator was connected or commissioned.
- No independent emergency stop, electrical interlock, manual override or actuator feedback has been verified on the actual farm.
- Local edge offline behavior and sync/recovery still require integration testing against the target edge hardware/network.
- Farm-specific sensor calibration, thresholds, transformer assignments and equipment inventory must be confirmed against actual installed equipment before operational use.
- The synthetic simulator is for software testing only; its readings must remain clearly identified as simulated.

## Safety boundary

All edge commands remain DRY_RUN records. The software never treats command approval or requested state as proof of physical actuation. Fresh telemetry may provide evidence for operator review but does not independently prove that an action caused a condition to resolve.
