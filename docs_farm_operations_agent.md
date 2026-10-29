# Aqua OS Farm Operations Agent — Initial Implementation

## What is implemented

The first agent vertical slice is a read-only, authenticated Farm Operations Agent that queries the existing pond and telemetry repositories. It returns a structured answer, the evidence used, the intent selected, evaluation time, and explicit limitations.

### API

- `GET /api/v1/agent/capabilities`
- `POST /api/v1/agent/query`

Example request body:

```json
{
  "farm_id": "farm-alpha",
  "question": "Which ponds have low dissolved oxygen or missing readings?"
}
```

The caller must authenticate with a bearer token and have `telemetry:read`. Farm access is verified before data access. The agent has no actuator, pump, aerator, feeder, dosing, or write tools.

## Current mode and limitations

- `DETERMINISTIC_READ_ONLY_MVP`: this first version routes common operator questions using deterministic intent selection. It is not yet an LLM-powered conversational agent.
- Current intents: farm overview, pond status, low-oxygen risk review, and telemetry freshness/health.
- Answers are grounded in latest repository telemetry and safety evaluations. Missing or stale readings are surfaced as unknown/degraded; they are not treated as safe.
- Simulation provenance is included in the evidence.
- Safety thresholds are inherited from the existing configured evaluator and still require validation against the actual farm.
- No physical actuator command path is exposed.

## Next implementation milestones

1. Add a provider-neutral LLM adapter that can be disabled or unavailable without interrupting deterministic safety logic.
2. Add conversation/session persistence with farm scoping, audit trail, and source-linked tool results.
3. Improve tool output presentation with typed per-domain summaries rather than raw JSON where the domain schema supports it.
4. Add server-side audit events for agent queries and tool names without logging secrets or unnecessary sensitive payloads.
5. Only after commissioning, consider narrowly scoped actuation proposals routed through a separate local safety gateway; never let an LLM directly operate equipment.

## Optional LLM response synthesis (v0.3)

The agent remains deterministic and read-only by default. To opt into LLM-assisted
wording, configure these environment variables in the API environment:

- `AQUA_AGENT_LLM_ENABLED=true`
- `AQUA_AGENT_LLM_API_KEY=<secret>`
- `AQUA_AGENT_LLM_BASE_URL=https://api.openai.com/v1` (optional; OpenAI-compatible endpoint)
- `AQUA_AGENT_LLM_MODEL=gpt-4o-mini` (optional)
- `AQUA_AGENT_LLM_TIMEOUT_SECONDS=12` (optional, bounded to 2–30 seconds)

Do not commit credentials. Enabling this feature sends the operator question and the
already-authorized agent result to the configured provider. Keep it disabled if farm
data must remain entirely on-premises. The LLM cannot select or execute tools, query
the database, or actuate equipment. Provider errors/timeouts fall back to the
pre-existing deterministic answer. Validate the provider, privacy terms, and data
residency before enabling it in production.

## Remaining work that requires separate implementation/verification

- Stateless conversations: persistent, farm-scoped history, retention controls, and audit events.
- Runtime verification: authenticated API integration, each domain tool against real configured data,
  role/tenant isolation, and browser interaction checks.
- Edge deployment: actual sensor/PLC protocol mapping, offline queue/recovery, watchdog and
  independently wired emergency-stop/interlocks.
- Physical commissioning: verify sensor calibration, electrical/motor assignments, fail-safe behavior,
  manual override, and actuator feedback before removing DRY_RUN.
- Farm-specific validation: confirm thresholds, hardware ratings, operating procedures, and
  disease/treatment guidance with qualified aquaculture staff and authoritative sources.


## Version 0.5 — persistent conversations and cross-module review

- Conversation history is persisted in `agent_conversations` and `agent_conversation_turns` and scoped by the authenticated `user_id` and `farm_id`.
- `POST /api/v1/agent/query` accepts an optional `conversation_id`; a new conversation is created when it is omitted.
- `GET /api/v1/agent/conversations`, `GET /api/v1/agent/conversations/{conversation_id}`, and `DELETE /api/v1/agent/conversations/{conversation_id}` support list, read, and delete for the authenticated user's own farm-scoped conversations.
- Conversation history is context only, never live farm evidence. Follow-up pond references are resolved only when obvious, and current telemetry/domain data is retrieved again for the answer.
- History is bounded to 40 turns per conversation, with each stored turn capped at 6,000 characters. Users can delete conversations from the dashboard.
- Explicit cross-module questions can retrieve a fixed allow-list of read-only domain services (actions, production, feed inventory, water, power, and, only with audit permission, working capital). Missing services are marked unavailable rather than treated as healthy.
- Physical actuation, treatment dosing, and autonomous safety-rule changes remain disabled.

### New verification status

SQLite in-memory CRUD and user/farm isolation checks passed for conversation storage. Intent-routing and contextual follow-up smoke assertions passed. Python compilation, dashboard JavaScript syntax, API client syntax, and duplicate HTML ID checks passed. Live API authentication, browser interactions, migrations against an existing farm database, and hardware behavior have not been verified in this environment.

## v0.6 — Evidence-linked Decision Review

- Cross-module reviews now include a deterministic `decision_review` object.
- Findings are extracted only from explicit action records returned by the authorized `farm_actions` tool; duplicate action IDs are collapsed and the more severe returned record is retained.
- Findings carry source tool, severity, pond/scope, category, reason, confidence, source timestamp, supporting evidence, and the source's own recommended next step.
- Failed source tools are listed as unavailable and set review status to `PARTIAL`; empty action lists do not mean the farm is healthy.
- Dashboard renders a readable decision-review section rather than requiring operators to infer priority from raw tool JSON.
- This feature is advisory-only. It does not approve or execute actions and does not control hardware.
- Fixed a missing `Optional` import in the SSE telemetry broadcaster that prevented application import during test collection.
- Verification: Python compileall, dashboard JS syntax check, and targeted decision-review tests. Full suite, live API/database and browser checks remain pending.

## Operator approval and outcome tracking (v0.7)

The agent now supports an audited operator decision workflow:

1. Create a review record from a source-backed finding (`POST /api/v1/agent/decisions`).
2. List farm-scoped records (`GET /api/v1/agent/decisions`).
3. Approve or reject a pending advisory (`POST /api/v1/agent/decisions/{decision_id}/review`).
4. Record a human-reported outcome for an approved advisory (`POST /api/v1/agent/decisions/{decision_id}/outcome`).

All routes verify farm access. Creating/reviewing/outcome recording requires `advisory:ack`; listing requires `telemetry:read`. Status transitions are constrained: `PENDING_REVIEW` -> `APPROVED` or `REJECTED`; only `APPROVED` can transition to `COMPLETED` through outcome recording. The finding snapshot and actor/timestamp event history are persisted in `agent_decisions`.

**Safety boundary:** approval is approval of an advisory/work item only. It does not authorize or execute equipment control. Outcome records are human-reported and do not constitute sensor-confirmed proof that a pond or device is safe. Physical actuation remains outside this workflow and must stay DRY_RUN until independent interlocks, emergency stop, manual override, device feedback, and commissioning are verified.

Dashboard integration: source-backed findings can be saved to the operator inbox; pending items can be approved/rejected; approved items can receive a human-reported outcome. Browser/runtime integration and authorization tests against a running installation remain required before production use.
