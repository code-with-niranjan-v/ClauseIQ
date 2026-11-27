# RegDesk workbench

RegDesk is the React frontend for ClauseIQ. Open `http://localhost:5173/workbench` for RegDesk or `http://localhost:5173/test` for the original pipeline testing dashboard. The overview, regulator watcher, PDF upload, findings, recommendations, and review history use live data through the Axios client in `src/api.js`. Vite and nginx both forward same-origin `/api` requests to the Spring Boot backend.

The workbench supports finding approval, editing and rejection, audit CSV export, and ingestion queue controls. The cited document pane shows the exact quote returned by the backend. Policy Q&A, schema discovery, and task delivery are visible and marked unavailable until there are backend endpoints for them.

## Frontend layout

- `src/App.jsx` contains the pipeline testing dashboard.
- `src/regdesk/RegDesk.jsx` contains the RegDesk layout and navigation.
- `src/regdesk/pages/` contains the seven RegDesk screens. Each screen has a direct URL under `/workbench`.
- `src/api.js` is the shared Axios client.

## Run locally

```sh
npm ci
npm run dev
```

The frontend expects the backend at `http://localhost:8080`. Set `VITE_BACKEND_URL` before starting Vite to change it.

From the repository root, rebuild only the frontend in a running Compose stack with:

```sh
docker compose up --build --no-deps -d --wait clauseiq-frontend
```

## Checks

```sh
npm run lint
npm run build
```
