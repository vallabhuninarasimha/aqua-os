# Aqua OS reference UI implementation

## Scope
- Reworked `apps/dashboard/index.html`, `apps/dashboard/css/dashboard.css`, and `apps/dashboard/js/dashboard.js` into a responsive four-view UI aligned to the supplied Aqua OS reference board.
- Views: TV Wallboard / Farm Overview, Owner Dashboard, Worker Field Companion, and Pond Detail & Equipment preview.
- Includes 20 sample pond cards, status badges, owner KPI cards, a canvas trend chart, searchable/filterable pond table, task checklist, Telugu/English voice-assistant visual placeholder, pond detail chart, and simulated equipment toggles.
- Uses existing local image assets from `apps/dashboard/assets/`.
- Preserved the prior HTML at `apps/dashboard/index.pre-reference-redesign.html`.

## Intentionally not connected
- No backend API calls are made by the new UI script.
- Sensor readings and trend lines are illustrative sample data, not live telemetry.
- Equipment toggles only change browser-preview state; they do not issue actuator commands.
- Voice capture, shrimp AI scan, alert notifications, persistence, offline sync, and emergency calling are placeholders.

## Checks performed
- `node --check apps/dashboard/js/dashboard.js` passed.
- Python HTML parser accepted `apps/dashboard/index.html`.
- Browser smoke test could not run in this environment because Chromium navigation to the local preview server was blocked by the runtime (`ERR_BLOCKED_BY_ADMINISTRATOR`).

## Start
Run the existing Aqua OS backend using the repository's normal setup. FastAPI serves this dashboard at `/` and maps `/static/` to `apps/dashboard/`.
