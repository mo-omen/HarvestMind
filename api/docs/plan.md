# AgriPivot Project Plan

## Product Goal

Build a decision intelligence system for farmers that helps them decide whether to:

- persevere with their current crop
- pivot part of their effort to another crop
- harvest early to protect revenue

The system should not just predict weather or prices. It should recommend a concrete course of action using multiple signals and explain why that recommendation makes sense.

## Core User Flow

1. A farmer enters a guided conversational intake flow.
2. The system extracts structured fields from each answer and asks only the next missing question.
3. Once the minimum decision payload is complete, the api gathers relevant market, weather, and regional news signals.
4. Deterministic tools analyze those signals and produce structured evidence.
5. The Z AI / GLM layer reasons over the evidence and returns a recommendation.
6. The system displays the decision, rationale, pricing outlook, risks, and suggested next steps.

## Inputs

### Farmer-provided inputs

- location
- current crop
- expected harvest window
- farm size
- labor flexibility
- irrigation or growing constraints when relevant
- risk preference if the team decides to include it
- optional candidate crops for switching

### Conversational intake behavior

- ask one focused question at a time
- convert free-text farmer answers into structured fields
- detect missing or ambiguous fields
- ask follow-up questions only when needed
- stop the intake once the minimum analysis payload is complete
- keep the final decision engine dependent on structured fields, not loose chat history

### External data inputs

- historical crop price data
- current market price snapshots
- price direction and price volatility signals
- current and short-term weather forecasts
- historical or seasonal weather patterns
- regional agriculture news
- pest outbreak reports
- trade, export, and policy news
- local market bulletins when available

## Data Used

### Structured data

- crop price time series
- current and recent market prices
- forecast rainfall and temperature
- farm profile data
- recommendation history

### Unstructured or semi-structured data

- news articles
- agriculture advisories
- pest alerts
- logistics and supply chain reports

### Derived internal data

- price trend signals
- price outlook classifications such as `increase`, `stable`, `decrease`
- revenue risk estimates
- weather risk scores
- event tags such as `oversupply`, `pest_risk`, `export_surge`
- scenario comparison results
- confidence scores
- review timing recommendations

## System Architecture

The product should be built as a tool-driven decision engine, not as a free-form autonomous agent.

### Main layers

- conversational intake layer
  Collects farmer context through guided questions and extracts structured fields
- input layer
  Receives normalized farmer input and external data
- tool layer
  Runs deterministic analytics first
- reasoning layer
  Uses Z AI / GLM to synthesize evidence into a recommendation
- output layer
  Returns structured JSON and human-readable explanation
- storage layer
  Stores profiles, signals, recommendation runs, and feedback
- worker layer
  Handles scheduled syncing of prices, weather, and news

## Main Analysis Tools

- `conversation_manager`
  Tracks intake progress and decides the next best question
- `field_extractor`
  Converts natural-language farmer answers into structured fields
- `missing_field_detector`
  Checks whether enough structured information exists to run analysis
- `price_analysis_tool`
  Detects rising, stable, or falling market conditions and produces a price outlook
- `weather_risk_tool`
  Measures weather-related disruption risk
- `news_signal_tool`
  Extracts useful events from unstructured regional information
- `scenario_compare_tool`
  Compares persevere vs pivot vs harvest early outcomes
- `recommendation_orchestrator`
  Builds the final evidence packet for the reasoning model

## Output

Each recommendation should include:

- decision: `persevere`, `pivot_partially`, or `harvest_early`
- price outlook: `increase`, `stable`, or `decrease`
- revenue risk level
- confidence score
- short recommendation summary
- top supporting reasons
- suggested actions
- risks or uncertainties
- next review timing

## Recommended Tech Stack

- `FastAPI` for api APIs
- `Postgres` for structured storage
- `Redis + Celery` for background jobs
- `React + Vite` for the frontend
- `Z AI / GLM` for structured reasoning
- `Open-Meteo` for weather data
- `FAO / FAOSTAT` and local sources for price data
- `GDELT` and optionally `Firecrawl` for news enrichment
- `pgvector` plus PostgreSQL full-text search if hybrid document retrieval is added

## Important Design Decision

This system should work as:

`conversation -> structured fields -> tools analyze -> GLM reasons -> recommendation out`

This is better than an autonomous agent design because it is easier to explain, easier to validate, and more aligned with hackathon judging around technical feasibility and system logic.

Hybrid retrieval is only for the news and advisory layer. Structured pricing and weather data should remain normal database queries.

## MVP Scope

The first working version should include:

- one guided conversational intake flow
- one main api endpoint for decision analysis
- price trend analysis
- price outlook and revenue risk in the final recommendation
- weather risk analysis
- news signal analysis
- one structured recommendation response
- one dashboard that shows the decision and explanation

## Current Project Status

The `AgriPivot/` project already contains:

- api scaffold
- frontend scaffold
- architecture note
- persisted intake sessions and structured profile storage
- persisted recommendation runs, feedback, signal snapshots, and sync jobs
- live weather retrieval via `Open-Meteo`
- live news retrieval and normalization via `GDELT`
- deterministic decision pipeline with scenario comparison and seasonal weather context
- demo UI for the recommendation flow
- **Full UI Redesign**: Refined Editorial Minimalist aesthetic implemented.
- **Dockerization**: Complete stack (App, DB, Redis) containerized.
- **Configurable LLM**: Support for custom base URLs (e.g., `ilmu.ai`).
- **Mem0 Cleanup**: Legacy Mem0 integration discarded and removed.

## Short Build Plan

### Phase 1 (Completed)

- finalize product framing
- define the core structured input fields
- define conversational intake questions and slot mapping
- lock the recommendation output format
- make pricing a required recommendation field
- **Editorial UI Redesign**

### Phase 2 (Completed)

- connect live weather retrieval with normalized snapshots
- implement live GDELT news retrieval and event tagging
- persist decision runs in the database
- add persisted intake sessions, farmer profiles, and feedback capture
- add operational sync and readiness endpoints
- **Dockerization of the full stack**

### Phase 3 (In Progress)

- replace deterministic fallback pricing with real market connectors and stored price history
- improve recommendation quality and explanation quality
- add hybrid retrieval over stored news and advisory documents
- improve conversational field extraction and follow-up logic
- expand scenario comparison into explicit revenue calculations

### Phase 4

- polish frontend for demo and expose the new api surfaces in the UI
- prepare PRD, system analysis, and pitch assets
- test end-to-end flows for the final presentation

## Future Roadmap (Missing Components)

1.  **Real Price Connectors**: Replace deterministic fallback pricing with FAOSTAT or local market ingestion and stored normalized price history.
2.  **Hybrid Retrieval for News**: Move from live-only GDELT fetches to stored documents plus retrieval over advisories and regional news.
3.  **Advanced Workers**: Add scheduled sync and alerting beyond the on-demand job endpoints that exist now.
4.  **ROI Calculation**: Add deterministic revenue and cost-of-pivot calculations for explicit crop comparisons.
5.  **Auth & Multi-Tenancy**: Implement OAuth2/JWT and a multi-user system for farmers and consultants.
6.  **Reporting**: Exportable PDF decision reports for banks and insurance providers.
