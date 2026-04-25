# Repository Guidelines

## Project Structure & Module Organization
The active app is a small Node.js server plus static HTML pages at the repository root. `server.js` serves the UI files and proxies `POST /api/chat` to the ILMU/GLM API. Root pages include `index.html`, `overview.html`, `markets.html`, and `crops.html`; keep navigation and visual changes consistent across them.

`api/` contains the FastAPI service. Its Python source lives under `api/app/`, with routes in `api/routes/`, domain logic in `services/`, external API clients in `clients/`, database access in `repositories/` and `db/`, and schemas in `schemas/`. SQL setup is in `api/sql/`.

## Build, Test, and Development Commands
- `npm start` or `node server.js`: start the root app on `http://localhost:3000`.
- `PORT=4000 API_KEY=... npm start`: run the root app on another port with a real API key.
- `docker compose up --build`: start the frontend, FastAPI api, Postgres, Redis, worker, and scheduler.

There is no build step for the root HTML app.

## Coding Style & Naming Conventions
Use 2-space indentation in JavaScript, HTML, CSS, JSON, and YAML. Prefer plain JavaScript and built-in Node modules unless a dependency is clearly needed. Keep page filenames lowercase and descriptive, such as `markets.html`. For Python in the api, follow PEP 8, use type hints where practical, and keep modules grouped by responsibility.

Do not commit generated files such as `__pycache__/`, local environment files, or dependency directories.

## Testing Guidelines
No automated test suite is currently configured. For root changes, run `npm start`, open each changed page, and exercise the chat flow if `server.js` or `/api/chat` changed. For api changes, add or run appropriate FastAPI/Python tests if introduced, and at minimum verify container startup with Docker Compose.

## Commit & Pull Request Guidelines
Recent history uses short imperative messages like `Update crops.html`. Keep commits focused and name the affected area, for example `Update market indicators` or `Fix chat proxy errors`.

Pull requests should include a summary, changed pages or api modules, manual test results, linked issues when applicable, and screenshots for visible UI changes. Mention required environment variables such as `API_KEY`, `ILMU_API_KEY`, or database settings when they affect review.

## Security & Configuration Tips
Never hard-code real API keys. Use environment variables for secrets, and avoid logging request payloads that may contain user or farm-specific data.
