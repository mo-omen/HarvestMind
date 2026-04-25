# AgriPivot Architecture

This prototype is intentionally shaped as a modular monolith.

## Open-source pieces worth using

- `FastAPI`: fast to scaffold, clean router structure, easy JSON APIs.
- `PostgreSQL`: source of truth for profiles, recommendation runs, and normalized signals.
- `PostGIS`: useful once you need district or radius-based matching for farms and regional news.
- `Redis + Celery`: good for scheduled ingestion and enrichment jobs.
- `React + Vite`: fast frontend iteration for a hackathon.

## Open-source pieces to treat as optional

- `pgvector`: useful if you want semantic retrieval over news documents.
- `Firecrawl`: good fallback when feeds and APIs are unavailable.
- `TimescaleDB`: useful after you have enough time-series volume to justify it.

## Pieces that add more hassle than value for the MVP

- Full autonomous agent runtimes as the main api.
- Heavy workflow engines like Temporal for a first hackathon build.
- A separate vector database before plain Postgres has become a bottleneck.

## Recommended shape

```text
frontend -> conversational intake -> FastAPI orchestration -> deterministic tools -> GLM decision layer
                                                    -> Postgres
                                                    -> Redis/Celery
```

## Implemented api surface

- `POST /api/v1/intake/message` for stateless guided intake turns
- `POST /api/v1/intake/sessions` and `POST /api/v1/intake/sessions/{session_id}/message` for persisted intake sessions
- `POST /api/v1/profiles` and `GET /api/v1/profiles/{farmer_id}` for structured farmer profiles
- `POST /api/v1/analysis/decision` for persisted recommendation runs
- `POST /api/v1/analysis/compare` for deterministic crop scenario comparison
- `GET /api/v1/recommendations/{farmer_id}` for recommendation history
- `POST /api/v1/feedback` for farmer feedback and outcome capture
- `GET /api/v1/signals/{farmer_id}/latest` and `/history` for normalized signal snapshots
- `GET /api/v1/health/ready` plus `POST /api/v1/ops/sync` for operational readiness and sync jobs

## Current data providers

- Weather: `Open-Meteo` with normalized forecast snapshots
- News: `GDELT` document API with article normalization and event tagging
- Pricing: deterministic fallback history only; this remains the main missing live connector
- Reasoning: `Z AI / GLM` when configured, with deterministic fallback recommendations when unavailable

## Data flow

1. Farmer answers guided intake questions in natural language.
2. Backend extracts structured fields and asks for only the missing information.
3. Intake state can be persisted server-side and resumed by session id.
4. Once the minimum payload is complete, api assembles price, weather, and news context.
5. Deterministic tools compute pricing, weather, seasonal timing, and comparison signals.
6. GLM turns those signals into a structured recommendation when configured.
7. Recommendation, signal snapshots, sync jobs, and later feedback are stored in Postgres.

## Persistence model

- `farmers`: structured farmer profile and latest intake context
- `intake_sessions`: resumable conversational intake state plus transcript
- `recommendation_runs`: decision inputs, evidence packet, and output metadata
- `recommendation_feedback`: farmer feedback and later outcomes
- `signal_snapshots`: normalized price, weather, and news snapshots
- `sync_jobs`: operational sync history for market, weather, and news refreshes

## Main architectural gap

The current architecture now matches the intended tool-driven flow for intake, evidence capture, and recommendation persistence, but pricing is still the weak point. The next meaningful architecture step is replacing deterministic market-price fallback data with real connectors and stored price history, then using that stored data as a first-class input to the comparison and revenue logic.
