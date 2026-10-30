# Aqua OS

AI-powered aquaculture monitoring, intelligence, and automation platform for commercial shrimp farming operations (*Litopenaeus vannamei* / *Penaeus monodon*).

Aqua OS is designed from the ground up for our **current 20-pond commercial operation**, with a configuration-driven Clean Architecture that scales seamlessly to additional ponds and future multi-farm deployments without application redesign.

---

## Architectural Principles

1. **Edge-First & Fail-Safe Sovereignty**: Dissolved Oxygen (DO) depletion can cause total crop mortality within 30–45 minutes. Safety-critical aerator loops run deterministically on the physical farm edge, independent of cloud connectivity.
2. **20-Pond Baseline with Scoped Identity**: The system starts with an operational baseline of 20 ponds (`pond-01` through `pond-20`). All entities are scoped by `farm_id` + `pond_id` to prevent multi-farm collisions.
3. **Clean Architecture & SOLID**: Strict separation between core Domain logic, Application routing, Infrastructure/Persistence, and Security. All repositories and identity providers are defined via protocols and injected at runtime.
4. **No Premature Complexity**: We prioritize free, open-source tools and local development. Database persistence defaults to SQLite locally and switches seamlessly to PostgreSQL/TimescaleDB in containerized environments. No Redis, Kubernetes, or paid services are required.
5. **Security as a Core Invariant**:
   - Authentication via replaceable identity provider (pluggable JWT/OAuth2).
   - Passwords hashed with PBKDF2-HMAC-SHA256 (100,000 iterations, 16-byte random salt). Plaintext credentials are never stored.
   - Granular RBAC (`viewer`, `operator`, `farm_manager`, `system_admin`) with deny-by-default access control.
   - Farm-level tenant isolation enforced at the backend.
   - Immutable security audit logging with secret redaction.
6. **Safety Non-Negotiable**: Missing, invalid, or faulted critical sensor readings (DO) are **never silently treated as safe**; they immediately trip `DEGRADED` or `CRITICAL` safety alerts. Recommendations remain strictly advisory in this milestone.

---

## Monorepo Layout

```
aqua-os/
├── apps/
│   └── api/
│       └── src/
│           ├── config.py              # Environment configuration & security settings
│           ├── dependencies.py        # FastAPI dependency injection providers
│           ├── main.py                # Application factory, lifespan, security headers, CORS
│           ├── domain/                # Core domain logic (zero external dependencies)
│           │   ├── interfaces.py      # IPondRepository, ITelemetryRepository, ISafetyEvaluator
│           │   └── safety.py          # Deterministic biological safety rules engine
│           ├── infrastructure/        # Persistence adapters & database models
│           │   ├── database.py        # SQLAlchemy engine, session maker, and seeders
│           │   ├── models.py          # SQLAlchemy ORM (ponds, telemetry, users, audit, tokens)
│           │   ├── migrations/        # PostgreSQL / TimescaleDB DDL & rollback scripts
│           │   └── repositories/      # Concrete SQL repository implementations
│           ├── security/              # Security and identity subsystem
│           │   ├── models.py          # UserIdentity, Role, Permission, Token schemas
│           │   ├── interfaces.py      # IIdentityProvider protocol
│           │   ├── password.py        # PBKDF2-HMAC password hashing & verification
│           │   ├── jwt_provider.py    # LocalJWTIdentityProvider with token lockout & revocation
│           │   ├── dependencies.py    # Auth dependencies (get_current_user, require_permission)
│           │   └── audit.py           # Security audit logging with secret sanitization
│           └── routes/                # API endpoints
│               ├── auth.py            # Login, logout, user profile
│               ├── health.py          # Liveness and readiness probes
│               ├── ponds.py           # Pond management & 20-pond overview
│               └── telemetry.py       # Sensor ingestion, latest cache, and historical query
├── packages/
│   └── telemetry_schema/              # Shared data contracts
│       ├── config.py                  # PondConfig, FarmConfig, biological thresholds
│       └── models.py                  # MetricReading, PondTelemetryPacket, ActuatorCommand
├── docker/
│   ├── docker-compose.yml             # Local dev stack (TimescaleDB & Mosquitto)
│   └── mosquitto/
│       └── config/
│           ├── mosquitto.conf         # Local dev MQTT broker configuration
│           ├── mosquitto.prod.conf.example # Production mTLS configuration template
│           └── acl.example            # Production farm topic isolation ACL template
├── scripts/
│   └── backup_restore.py              # Automated database backup, restore & verification tool
├── tests/                             # Automated test suite (38 unit, integration & security tests)
│   ├── conftest.py                    # Test fixtures, database lifecycle & auth tokens
│   ├── test_backup_restore.py         # Disaster recovery & database restore verification
│   ├── test_pond_registry.py          # 20-pond baseline, expansion, and persistence tests
│   ├── test_schemas.py                # Schema validation & physical bounds tests
│   ├── test_security.py               # Auth, RBAC, lockout, cross-farm isolation tests
│   └── test_telemetry_api.py          # Protected endpoints, safety rules, and history tests
├── pyproject.toml                     # Pytest, ruff, and tool configuration
└── README.md                          # Project documentation & operational runbook
```

---

## Local Development & Setup

### Prerequisites
- Python 3.12+
- Docker & Docker Compose (optional for PostgreSQL/TimescaleDB and Mosquitto)

### 1. Environment Setup

```bash
pip install fastapi uvicorn pydantic pydantic-settings httpx pytest ruff sqlalchemy pyjwt
```

### 2. Running Local Development Infrastructure (Optional)

To run containerized TimescaleDB (PostgreSQL 16) and Eclipse Mosquitto:
```bash
docker compose -f docker/docker-compose.yml up -d
```

### 3. Running the FastAPI Application & Local Monitoring Dashboard

Start the backend API server and local monitoring dashboard with auto-reload:
```bash
python -m uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8000 --reload
```

Access points:
- **Local Realtime Dashboard:** `http://localhost:8000/` (100% offline-first, zero external CDNs)
- **Interactive Swagger UI:** `http://localhost:8000/docs`
- **ReDoc Documentation:** `http://localhost:8000/redoc`

Default development seed credentials:
| Username | Password | Role | Farm |
| :--- | :--- | :--- | :--- |
| `admin` | `admin_secret_123` | `system_admin` | Global / All farms |
| `operator` | `operator_secret_123` | `operator` | `farm-alpha` |
| `viewer` | `viewer_secret_123` | `viewer` | `farm-alpha` |
| `beta_operator` | `beta_secret_123` | `operator` | `farm-beta` |

---

### 4. Operating the Farm Dashboard

1. Start the API and open `http://localhost:8000/`.
2. Sign in with an authenticated farm account. The dashboard reads the farm's persisted API data; it does not generate browser-side pond readings.
3. Pond cards and alerts are populated from the authenticated dashboard API and live telemetry stream. Missing or stale sensor data must remain visibly unavailable/degraded; it is not treated as a healthy reading.
4. Historical trends are shown only when persisted telemetry history exists.
5. Physical equipment remains unavailable until the edge gateway, actuator feedback, electrical protections, emergency stop, and commissioning checks have been verified on site.

The standalone simulator below is a development/engineering tool only. It is not started by the production API and must never be presented as live farm telemetry.

### 5. AI, Biological Intelligence & Operator Workflow

Aqua OS combines deterministic domain engines with an optional evidence-grounded language model:
- **Farm Operations Agent**: authenticated, farm-scoped, read-only tool routing across pond telemetry, low-oxygen risk, sensor freshness, production, feed inventory, water, power, health, and cross-module farm actions.
- **Decision review**: source-linked advisory findings with severity, confidence, provenance, operator approval/rejection, and outcome tracking. LLM text cannot issue actuator commands or change biological safety thresholds.
- **Feeding intelligence**: biomass- and sample-aware ration recommendations with DO/temperature/tray feedback. Feed plans remain subject to operator review and approval.
- **Aeration and safety**: deterministic threshold evaluation and local edge sovereignty are the safety authority. AI may explain evidence and recommend review; it does not replace the safety engine.
- **Shrimp health and production**: mortality, clinical observations, growth samples, biomass estimates, FCR, harvest projections, and treatment withdrawal restrictions remain distinct evidence-backed records.
- **Shrimp size grading**: `POST /api/v1/production/ponds/{pond_id}/grading/analyze` classifies individually weighed sample shrimp using operator-configured count-per-kg bands. The response includes average body weight, count/kg, size distribution, and unclassified sample count. Grade bands are buyer/farm-specific and must be configured by the operator.

The grading endpoint accepts a list of individual weights in grams and explicit non-overlapping grade bands. It does not claim camera-based recognition, whole-pond grade, or harvest readiness. Camera-based grading requires a commissioned camera, controlled image capture, a validated vision model, and field calibration; none is inferred from sample weights.

### 6. Running the 20-Pond Telemetry Simulator CLI


Launch the standalone deterministic multi-pond physics simulator:
```bash
python tools/simulators/run_sim.py --ponds 20 --interval 2.0 --seed 42 --fault-pond pond-03
```
Options:
- `--ponds`: Number of simulated ponds (default: `20`).
- `--interval`: Step interval in seconds (default: `2.0`).
- `--seed`: Pseudorandom seed for reproducible physics & noise (default: `42`).
- `--fault-pond`: Pond ID to inject an aerator failure scenario into for testing (default: `pond-03`).

### 7. Running the Sovereign Edge Runtime Daemon

Launch the edge store-and-forward gateway daemon:
```bash
python apps/edge/src/run_edge.py
```
Key Edge Features:
- **Local Sovereignty:** Evaluates safety rules deterministically on the edge gateway without requiring an active internet connection.
- **SQLite WAL Persistence:** Stores incoming telemetry in write-ahead log (`WAL`) mode with `NORMAL` synchronicity to ensure zero packet loss on abrupt power cuts.
- **Idempotent Queueing:** Uses SHA-256 deduplication hashing to ensure no duplicate sync entries occur upon MQTT QoS 1 retries.
- **Bounded Buffer Guardrail:** Configurable `max_queue_depth` guardrail prevents silent buffer overflow and runaway memory exhaustion during extended outages.

---

## Automated Testing & Quality Checks

Run the complete test suite (60 unit, integration, persistence, edge sovereignty, security, and dashboard API tests):
```bash
python -m pytest tests/ -v
```

Run code formatting and linter checks:
```bash
python -m ruff check .
```

---

## Security & Production Readiness

### Development Defaults vs. Production Requirements

| Component | Local Development Default | Production Requirement |
| :--- | :--- | :--- |
| **Database** | SQLite file (`sqlite:///aqua_os.db`) | Managed PostgreSQL 16 + TimescaleDB with automated WAL snapshots |
| **JWT Secret** | Development fallback string | Cryptographically random 64-char key provided via `AQUA_JWT_SECRET_KEY` |
| **CORS Origins** | `localhost:3000`, `127.0.0.1:3000` | Strictly bounded production domain via `AQUA_CORS_ORIGINS` |
| **MQTT Broker** | Port 1883 with `allow_anonymous true` | Port 8883 with mTLS X.509 certs, `allow_anonymous false`, password and ACL file |
| **Backups** | `scripts/backup_restore.py` | Automated cron snapshot with offsite S3-compatible replication and periodic restore rehearsal |

---

## Disaster Recovery & Database Restoration

To take an atomic database backup and verify table counts:
```python
from pathlib import Path
from scripts.backup_restore import backup_sqlite, verify_sqlite_backup, restore_sqlite_backup

backup_path = backup_sqlite(Path("aqua_os.db"), Path("backups"))
counts = verify_sqlite_backup(backup_path)
print(f"Backup verified: {counts}")
```

---

## Biological Threshold Calibration Notice

> [!NOTE]
> All biological thresholds (DO minimums, pH ranges, water temperature, salinity) in `packages/telemetry_schema/config.py` reflect provisional baseline standards for *Litopenaeus vannamei*. They must be calibrated against on-site water chemistry, local pond bathymetry, stocking densities, and historical phytoplankton bloom cycles before real automation is activated.