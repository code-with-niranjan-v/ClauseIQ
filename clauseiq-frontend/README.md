# ClauseIQ frontend

The React frontend for ClauseIQ. Open `http://localhost:5173/workbench` for the ClauseIQ workbench or `http://localhost:5173/test` for the original pipeline testing dashboard. Both use live data through the Axios client in `src/api.js`. Vite and nginx forward same-origin `/api` requests to the Spring Boot backend.

Every page requires sign-in. The session cookie and the `XSRF-TOKEN` cookie are set by the backend, and Axios returns the CSRF token in the `X-XSRF-TOKEN` header. Viewers can read and ask Policy Q&A; reviewers can also review, upload, scan and confirm circular changes; administrators can also manage users.

## Frontend layout

- `src/auth.jsx` is the sign-in gate, and `src/authContext.js` provides the signed-in user to components.
- `src/App.jsx` contains the pipeline testing dashboard.
- `src/workbench/Workbench.jsx` contains the workbench layout and navigation.
- `src/workbench/pages/` contains the workbench screens: overview, ingest, review, gaps and mapping, action plan, audit trail, system assessment, circular changes, data discovery, extraction quality and, for administrators, users. Each has a direct URL under `/workbench`.
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
