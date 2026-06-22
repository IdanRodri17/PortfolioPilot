# PortfolioPilot V9 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Captures V9 (backend JWT
> verification): closing the gap where the backend trusted a `user_id`
> query/path param. Sequenced after V10–V14 by request, but it is the
> default-closed baseline the V15 demo/share routes will explicitly opt out of.

**Status:** Shipped (code complete; backend enforcement verified live). The `v9`
tag is **pending the live browser smoke test** — confirming the logged-in app
still works end to end now that every user-data call must carry a token. The
rejection paths were verified live (see below). Code is committed on `main`.

**Headline:** the backend no longer trusts the request. Every user-scoped
endpoint derives the user from a verified token, so a raw
`curl ...?user_id=anything` is now rejected (401/422) instead of streaming
someone else's data.

**Decision (the build spec said decide this first):** Auth.js v5 stores its
session as an **encrypted JWE** cookie, so the backend can't verify it with the
secret alone. Rather than couple the backend to Auth.js internals by decrypting
that, the frontend mints a **separate, plain HS256 token** signed with the
shared `AUTH_SECRET`; the backend verifies it with PyJWT. Decoupled and standard.

**Smoke tests — verified in the build session:**

- **Auth dep (offline unit):** valid token → user_id; missing / wrong-signature
  / expired / no-subject / `alg=none` → 401; owner mismatch → 403.
- **Enforcement (live curl, no LLM):** `generate-report` with no token → 422,
  bad token → 401; `reports/history`, `reports/series`, `portfolio` (GET),
  `memories` (DELETE) with no token → 401; `GET /api/reports/{id}` (capability)
  → 200; `/api/health` → 200. History returning 401 (not 500) confirms the
  backend loaded the shared `AUTH_SECRET`.
- **Frontend:** `npx tsc --noEmit` + `eslint` clean.

**Smoke tests — pending your live run (browser):**

- Logged in, the dashboard/portfolio/history/settings/memory pages all still
  load and act (the token rides along automatically); **Generate report** works;
  the report **chat** works.
- A logged-out `curl ".../api/generate-report?user_id=idan_demo"` is rejected
  (already confirmed above).

---

## What was built

### V9a — backend verification (non-breaking)

```
backend/app/
├── core/config.py    # + optional auth_secret
├── api/deps.py        # NEW: verify_token, require_user, require_owner
└── requirements.txt  # + pyjwt (already present transitively; pinned for clarity)
```

`verify_token(raw)` decodes an HS256 token against `auth_secret` and returns its
`sub` (the user_id) — 401 on missing/malformed/expired/sub-less, 500 if the
secret is unconfigured. `require_user` reads the Bearer header;
`require_owner` resolves the endpoint's `user_id` path/query param and 403s on a
mismatch — so one `Depends(require_owner)` enforces ownership without per-handler
code.

### V9b — frontend token mint + attach (non-breaking)

```
frontend/src/
├── app/api/token/route.ts  # NEW: signs a 5-min HS256 token from the session (node:crypto)
├── lib/api.ts              # getApiToken (cached) + authHeaders; Bearer on user calls
├── lib/useReportStream.ts  # generate SSE carries ?token=...; resume sends Bearer
└── app/settings/page.tsx   # Bearer on run-now
```

The Next `/api/token` route reads the Auth.js session server-side and signs a
short-lived token with `AUTH_SECRET` using Node's built-in crypto (no new npm
dependency). The client caches it (refreshes a minute before expiry) and attaches
it to every user-scoped call. `getReport` (capability URL) and `validateTicker`
(public) stay unauthenticated.

### V9c — flip enforcement + share the secret

```
backend/app/api/{generate,portfolio,reports,memories,telegram,delivery,deliveries}.py
docker-compose.yml   # backend env_file += ./frontend/.env.local  (shares AUTH_SECRET)
```

Guards applied: generate (query-token + owner), resume (Bearer), portfolio
GET (owner) / POST (body user_id == token), reports history+series (owner) and
ask (report owner), memories GET+DELETE (owner), delivery GET+PUT (owner),
telegram connect (owner), deliveries run-now (owner). `GET /api/reports/{id}`
stays a capability URL; `run-due-deliveries` stays open (non-user cron trigger).

---

## Deviations / decisions

| Area | Choice | Why |
|---|---|---|
| Session verification | separate plain HS256 token, not Auth.js JWE | decouples the backend from Auth.js internals |
| SSE auth | short-lived **query token** (option A) | EventSource can't set headers; keeps the V12b/V13/V14 stream handlers intact. A `fetch`+reader refactor (option B) was the alternative |
| report-by-id | stays a public **capability URL** | uuid4 is unguessable; V15 public sharing reuses it |
| run-due-deliveries | left **open** | not user-scoped; the scheduler calls it in-process, not over HTTP; protect at the proxy in prod |
| PyJWT | pinned in requirements, **but no rebuild was needed** | it was already present transitively (2.13.0); the pin is for reproducibility |
| Secret sharing | compose `env_file: ./frontend/.env.local` on the backend | one secret, no copy, never in git; host-dev needs `AUTH_SECRET` in `backend/.env` |
| `v9` tag | deferred | pending the live logged-in browser smoke test |

---

## Explicitly deferred

- **Live browser confirmation + `v9` tag**, then flip the README build-status
  row from "🚧 In progress" to "✅ Shipped".
- **Resume ownership.** resume-graph requires a valid token but checks only
  authentication, not that the thread_id's report belongs to the caller
  (thread_id is an unguessable uuid). A full owner check would load the report.
- **Timing-attack hardening on /api/auth/verify** (V8 carry-over).
- **Token refresh on 401.** The client caches a 5-min token; a call that races
  expiry just fails and the next retry mints a fresh one. A 401-triggered
  re-mint+retry would be smoother.

---

## Patterns established

73. **Separate plain token, not the session cookie.** The frontend mints a
    short-lived HS256 token from the verified session (Next route, node:crypto);
    the backend verifies a standard token with the shared secret. No coupling to
    the auth library's encrypted cookie format.

74. **Identity from the token, ownership via one dependency.** `require_owner`
    resolves the endpoint's `user_id` path/query param and compares it to the
    token — `Depends(require_owner)` enforces "only your own data" across many
    endpoints with no per-handler code.

75. **One verify core, two transports.** `verify_token()` is shared by the
    header path (`require_user`) and the SSE query-token path, so the EventSource
    leg (which can't send headers) authenticates the same way.

76. **Capability-URL vs owner-gated policy.** Unguessable uuid4 reads stay public
    (sharing); user_id-keyed and cost-incurring endpoints are gated. This is the
    default-closed baseline V15 opts out of for demo/share.

77. **Share a secret across services via compose env_file.** Feeding
    `./frontend/.env.local` to the backend service gives both sides the same
    `AUTH_SECRET` with no duplication and nothing new in git.

*(Patterns #1–#72 from V1–V14 remain in force.)*

---

## Environment notes for the next Claude

- **AUTH_SECRET must match on both sides.** Docker: the backend reads it from
  `frontend/.env.local` via compose `env_file`. Host-dev: add the same
  `AUTH_SECRET` to `backend/.env`, or guarded routes 500 ("auth not configured").
- **No rebuild was needed** for V9 (PyJWT already in the image); a future clean
  rebuild will pick up the pinned `pyjwt`. The backend container was *recreated*
  (`docker compose up -d backend`) to load the new env_file.
- **The token is short-lived (5 min), cached client-side.** `/api/token` is
  gated by the existing middleware (authed requests pass; the cookie rides
  same-origin).
- **The SSE generate token is a query param** (`?token=...`) — short-lived to
  limit URL-leak exposure; everything else uses the `Authorization` header.

---

## V9 git history

```
feat(v9): backend JWT auth dependency
feat(v9): mint and attach a bearer API token from the frontend
feat(v9): enforce token auth on the user-data endpoints
docs(v9): add V9 implementation brief
(tag) v9  — pending live browser smoke test
```

To reconstruct the V9 baseline at any point once tagged: `git checkout v9`.
