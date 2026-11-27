# ClauseIQ frontend

One page that shows the whole pipeline, top to bottom, and refreshes every 10 seconds:

1. Scan regulator sources, with a "Scan now" button per source.
2. Read each circular, with its processing status.
3. Extract obligations, each with its quoted source text, page and clause.
4. Compare with policies and controls, with the coverage status and the reason.
5. Review findings. Open a finding to see the evidence and the drafted fix, then approve, edit or reject it.

"Show only this" on a circular limits stages 3 to 5 to that circular.

## Run

The page calls `/api` on its own origin. In development, Vite forwards those calls to the backend.

```sh
npm ci
npm run dev
```

Open `http://localhost:5173/test`. The backend is expected at `http://localhost:8080`. To use another address, set `VITE_BACKEND_URL` before `npm run dev`.

With Docker, the root `compose.yaml` serves the built page on `http://localhost:5173/test` through nginx, which forwards `/api` to the backend.

## Checks

```sh
npm run lint
npm run build
```
