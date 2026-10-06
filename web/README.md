# Tameio web (new frontend)

React + TypeScript PWA that replaces the Jinja/HTMX UI. Design source: `../docs/redesign/mocks/` (Vault direction).

- `npm run dev`: Vite on :5173, proxies `/api` to FastAPI on :8000 (run `uvicorn app.main:app` from the repo root).
- `npm run build`: outputs `dist/`, served under `/app/` until cutover.

Not part of the production Docker image yet (see `../.dockerignore`).
