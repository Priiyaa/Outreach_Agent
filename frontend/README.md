# Frontend

Next.js (App Router) + TypeScript + Tailwind + TanStack Query. All data comes from the FastAPI backend.

```bash
npm install
cp .env.example .env.local     # API address, default http://localhost:8000
npm run dev                    # http://localhost:3000 (start the backend too)
npm test                       # vitest + Testing Library
npm run typecheck && npm run lint && npm run build
npm run gen:api                # regenerate src/lib/api-types.ts after changing the backend's API
```

`src/lib/api-types.ts` is generated from the backend's OpenAPI spec, so the frontend's types cannot drift from the
API: change a response in `backend/app/api/schemas.py`, run `gen:api`, and TypeScript flags every place that breaks.

Layout: `src/lib` (API client, filter model), `src/components` (views and controls), `src/app` (routes, kept thin).
