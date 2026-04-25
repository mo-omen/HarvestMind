# HarvestMind (AgriPivot) - Decision Intelligence for Farmers

HarvestMind is a decision intelligence platform designed to help Malaysian farmers make data-driven decisions (persevere, pivot, or harvest early) using AI reasoning grounded in real-time market, weather, and news data.

## Project Overview

- **Core Mission:** Provide actionable intelligence to farmers to mitigate risks from weather events, market fluctuations, and news signals.
- **Primary Tech Stack:**
  - **Frontend:** Node.js static server (proxy) with pure HTML/CSS/Vanilla JS.
  - **Backend:** Python FastAPI (Modular Monolith).
  - **Intelligence:** ILMU GLM (Google Gemini-based) for conversational intake and structured recommendations.
  - **Data Persistence:** PostgreSQL (with PostGIS extensions intended).
  - **Task Queue:** Celery + Redis for scheduled data ingestion and background processing.
  - **Infrastructure:** Docker Compose for full-stack orchestration.

## Architecture & Data Flow

1.  **Conversational Intake:** Farmers interact with a GLM-powered chat that guides them through providing farm data (location, crops, harvest dates).
2.  **Field Extraction:** The backend extracts structured data from the conversation and identifies missing information.
3.  **Tool Enrichment:** Once a profile is complete, deterministic tools fetch and normalize:
    - **Weather:** Forecasts via Open-Meteo.
    - **News:** Event signals via GDELT.
    - **Market:** Pricing data (currently history-based fallback).
4.  **Reasoning Layer:** The enriched context (evidence packet) is sent back to the GLM to generate a structured recommendation.
5.  **Persistence:** Profiles, intake sessions, recommendation history, and signal snapshots are stored in PostgreSQL.

## Getting Started

### Prerequisites
- Docker and Docker Compose
- ILMU API Key (for GLM reasoning)

### Setup & Run
1.  **Environment:** Copy the example environment files.
    ```bash
    cp .env.example .env
    # Optionally if api has specific needs
    cp api/.env.example api/.env
    ```
2.  **Launch:** Start the full stack using Docker.
    ```bash
    docker compose up --build
    ```
3.  **Access:**
    - Frontend: [http://localhost:3000](http://localhost:3000)
    - Backend API: [http://localhost:8000/api/v1](http://localhost:8000/api/v1)
    - Interactive API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Project Structure

- `/` (Root): Frontend HTML files and `server.js` (proxy server).
- `/api/app/`: Core FastAPI application logic.
  - `/api/routes/`: REST API endpoints.
  - `/api/intake/`: Conversational state management and extraction logic.
  - `/api/tools/`: Data enrichment tools (weather, news, prices).
  - `/api/repositories/`: Database access layer (Repository pattern).
  - `/api/services/`: Business logic and orchestration.
  - `/api/workers/`: Celery task definitions.
- `/api/sql/`: Database initialization scripts.

## Development Conventions

- **Python Version:** 3.11+
- **Database:** Use the Repository pattern for all database interactions.
- **Schemas:** All API models and internal data structures use Pydantic.
- **Background Jobs:** Long-running syncs or periodic tasks must be implemented as Celery tasks in `api/app/workers/`.
- **Frontend:** Keep it simple with Vanilla JS and minimal dependencies. The Node server acts as a proxy to avoid CORS issues and protect the API key.
- **Mocking:** For local development without an ILMU key, the system is designed to have deterministic fallbacks, but an active key is recommended for testing the "intelligence" layer.
