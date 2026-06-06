# PortfolioPilot V8 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Captures what was built across V8
> (V8a NextAuth.js setup, V8b session-derived user_id + logout), what deviated
> from the V8 plan, and what was explicitly deferred — so any subsequent Claude
> conversation picks up with full context.

**Status:** Shipped. Tagged `v8` on `main`. Pushed to
`github.com/IdanRodri17/PortfolioPilot`.

**Headline:** the hardcoded `idan_demo` is gone. Real credential-based
multi-user auth now gates the entire frontend; every `user_id` reference is
derived from the authenticated session. The graph, delivery scheduler, and all
backend endpoints are untouched and remain V7-stable.

**Smoke tests passed:**

- **V8a backend verify:** `POST /api/auth/verify` with the seeded
  `idan101012@gmail.com` + correct password returns
  `{user_id, name, email}`; a wrong password and an unknown email both return
  an identical `401 {"detail":"Invalid email or password"}` (no enumeration).
- **V8a hash storage:** `hashed_password` column added to `users` via surgical
  `ALTER TABLE` (no data loss); seeded with a bcrypt `$2b$12$…` 60-char hash.
  Verified `prefix = $2b$12$`, `len = 60` after a Git-Bash `$`-escaping mishap
  was corrected via a heredoc seed.
- **V8a NextAuth wiring:** `GET /api/auth/session` returns `null` when logged
  out; `GET /api/auth/providers` lists the `credentials` provider with its
  signin/callback URLs. `npx tsc --noEmit` clean (session.user.id augmentation
  resolves).
- **V8a route protection:** an incognito hit on `/`, `/portfolio`, `/settings`
  redirects to `/login?callbackUrl=…`; `/login` itself renders without a loop;
  wrong password shows an inline error; correct password lands on the dashboard
  and the session persists across reloads.
- **V8b id swap:** all five pages load their data via `session.user.id`;
  `grep -rn '"idan_demo"' src/` returns nothing (only prose mentions of the
  string remain in comments/docstrings). Generate, portfolio save, history,
  memory wipe, settings save/connect/send-now all work unchanged.
- **V8b logout:** the dashboard nav shows the authenticated email and a
  Sign out control; clicking it clears the session and redirects to `/login`;
  navigating to `/` afterward bounces back to `/login` (session genuinely gone).

---

## What was built

### V8a — NextAuth.js (Auth.js v5) setup

```
backend/
├── app/
│   ├── db/models.py          # + hashed_password column on User (nullable)
│   ├── schemas/auth.py       # NEW: AuthVerifyRequest / AuthVerifyResponse
│   │                         #   (plain str email — no email-validator dep)
│   ├── api/auth.py           # NEW: POST /api/auth/verify (bcrypt.checkpw)
│   └── main.py               # + auth_router include
└── requirements.txt          # + bcrypt

frontend/
├── src/
│   ├── lib/auth.ts                         # NEW: NextAuth v5 config
│   ├── app/api/auth/[...nextauth]/route.ts # NEW: re-exports handlers
│   ├── types/next-auth.d.ts                # NEW: Session/JWT id augmentation
│   ├── app/providers.tsx                   # NEW: SessionProvider wrapper
│   ├── app/layout.tsx                      # + <Providers>; real metadata
│   ├── app/login/page.tsx                  # NEW: credential sign-in page
│   └── middleware.ts                       # NEW: route protection
├── .env.local                # + AUTH_SECRET (gitignored)
└── package.json              # + next-auth@beta (v5)
```

**Auth model — no DB adapter, backend is the data layer.** The typical v5
tutorial wires a Prisma/Drizzle adapter so NextAuth reads users directly. We
deliberately don't: the FastAPI backend already owns the users table, so the
Credentials provider's `authorize()` POSTs the email+password to
`POST /api/auth/verify` and the bcrypt check happens in Python. The Next.js
process never touches Postgres and never sees the password hash. This keeps a
single source of truth for identity (the backend) and a single place the hash
lives.

**Password storage.** bcrypt (`$2b$12$…`): one-way (login hashes the input and
compares, never decrypts), salted (per-user random salt defeats rainbow
tables), and slow by design (cost factor 12). `hashed_password` is nullable so
pre-auth rows and any future seedless users don't break — a null hash simply
means "can't log in with a password," handled as a 401.

**Session strategy is JWT** (required with no adapter). On sign-in the `jwt`
callback stashes `user_id` onto the token; the `session` callback copies it to
`session.user.id`. That single value is what every frontend call now keys on.
The token is signed with `AUTH_SECRET` and stored in a browser cookie.

**Route protection via middleware.** `src/middleware.ts` uses v5's `auth`
wrapper to gate every route at the edge. The matcher excludes `/login`,
`/api/auth/*`, and static assets to avoid a redirect loop. Unauthenticated
requests get bounced to `/login?callbackUrl=<where they were going>`.

### V8b — Session-derived user_id + logout

```
frontend/src/
├── lib/useUserId.ts          # NEW: { userId, loading } from useSession()
└── app/
    ├── page.tsx              # DEMO_USER → useUserId; + email + Sign out button
    ├── portfolio/page.tsx    # DEMO_USER → useUserId (load + save)
    ├── history/page.tsx      # DEMO_USER → useUserId (load)
    ├── memory/page.tsx       # DEMO_USER → useUserId (load + wipe)
    └── settings/page.tsx     # USER_ID → useUserId (load + save + connect + run-now)
```

`useUserId()` centralizes the `useSession()` access and the "session still
resolving" window: it returns `userId` (the id once authenticated, else null)
and `loading`. Each page calls it as the **first line in the component body**
(a hook outside the body throws "Invalid hook call" — hit once during dev) and
gates its data-fetch `useEffect` on a non-null `userId` (`if (!userId) return;`
with `userId` in the dep array). Handlers that fire only after render (save,
wipe, connect, run-now) use `userId!` since a session is guaranteed by then.

The dashboard nav additionally shows `session.user.email` and a Sign out button
(`signOut({ callbackUrl: "/login" })`), matching the inline-nav link style.

---

## Deviations from the V8 plan

| Area | Plan | V8 actually does | Why |
|---|---|---|---|
| Auth library | "Install next-auth" (version unspecified) | **Auth.js v5 (`next-auth@beta`)** | Next 16 + React 19 — v4 doesn't officially support them; v5 is built for the App Router. |
| Secret env var | (unspecified) | **`AUTH_SECRET`**, not v4's `NEXTAUTH_SECRET` | v5 reads `AUTH_SECRET`. Note: `npx auth secret` now emits `BETTER_AUTH_SECRET` (Better Auth stewards Auth.js) — that name is wrong for `next-auth`; set `AUTH_SECRET` manually. |
| DB adapter | (implied by NextAuth tutorials) | **None** — backend `/api/auth/verify` is the data access | Single source of truth for identity; the hash never leaves Python. |
| Email type | (unspecified) | **`str`, not Pydantic `EmailStr`** | The project never pulls in `email-validator`; the bcrypt check gates login, not RFC-correctness. A malformed email just 401s. |
| Seed mechanism | "seed idan_demo with a known password" | **psql heredoc with a bcrypt hash generated in the venv** | A `-c` with hand-escaped `\$2b\$12\$` got mangled by Git Bash (stored a 38-char fragment). A heredoc expands the shell var once and hands psql the literal 60-char string. |
| V8c backend token check | "optional but nice" | **Deferred to V9** (see below) | The report stream uses native `EventSource`, which can't send `Authorization` headers — a real `useReportStream` rewrite. Scoped out of V8; first item of V9. |

---

## Explicitly deferred (build in noted version)

- **V9 — Backend JWT verification (the big one).** Today the backend trusts the
  `user_id` in the request (query param or path). The frontend is gated, but a
  direct `curl http://localhost:8000/api/generate-report?user_id=<anything>`
  bypasses auth entirely — the FastAPI side has no guard. V9 should:
  1. Send the session token from frontend → backend (header for fetch calls;
     for the SSE generate leg, either a query-param token or — preferred —
     convert `useReportStream`'s `start()` from `EventSource` to the
     `fetch`+`getReader()`+`parseSseBlock` pattern its `resume()` leg already
     uses, so an `Authorization: Bearer` header can ride along).
  2. Verify the token backend-side with the shared `AUTH_SECRET` (`pyjwt` or
     `python-jose`) in a FastAPI dependency that extracts `user_id` from the
     **verified token**, not the request, and 401s on mismatch/absence.
  3. Note the v5 wrinkle: the default session token is encrypted (JWE), so the
     backend must decrypt with the same secret, OR `auth.ts` mints a separate
     plain JWT for API use. Decide this first — it shapes everything else.
  Apply the dependency to `generate`, `resume`, and the delivery endpoints.
- **V9 — Containerization + deployment.** Dockerfile(s) for backend and
  frontend; a `docker-compose.yml` that brings up Postgres (pgvector) + backend
  + frontend together; then a real deploy. Note the current compose only runs
  Postgres (service name `postgres`, container `portfoliopilot-postgres`, user
  /db/password all `portfoliopilot`). Deployment must add the deployed
  frontend origin to `_ALLOWED_ORIGINS` in `main.py` (currently hardcoded
  localhost:3000) and set `PUBLIC_APP_BASE_URL` to the deployed URL.
- **User profile page / signup** — editing `User.email`, a registration flow
  that writes `hashed_password` (currently seeded via psql). No self-serve
  account creation yet.
- **Timing-attack hardening on verify** — the unknown-email path returns
  slightly faster (no hash to check). A dummy-hash compare closes the channel;
  not worth it for the demo, noted for completeness.

---

## Patterns established — load-bearing for V9+

52. **Backend-as-auth-provider (no NextAuth adapter):** the Credentials
    `authorize()` calls `POST /api/auth/verify`; bcrypt verification and the
    users table stay entirely in Python. The frontend holds a signed session
    but never the hash. One source of truth for identity.

53. **Session-derived id via a single hook:** `useUserId()` wraps
    `useSession()` and surfaces `{ userId, loading }`. Pages gate data fetches
    on a resolved `userId` rather than reading the session ad hoc. The hook is
    the one place the "session still loading" window is handled.

54. **Edge-safe middleware gate:** v5's `auth` wrapper protects routes before
    render (no flash of protected content, no per-page guard). The matcher must
    exclude the redirect target (`/login`), NextAuth's own `/api/auth/*`, and
    static assets — omitting any of those causes a redirect loop. `authorize()`
    (which does a Node-only `fetch`) never runs in middleware; only the JWT
    cookie is read there, so the edge runtime is fine.

*(Patterns #1–#51 from V1–V7 remain in force.)*

---

## Environment notes for the next Claude

- **`AUTH_SECRET`** lives in `frontend/.env.local` (gitignored). Not
  `NEXTAUTH_SECRET` (v4) and not `BETTER_AUTH_SECRET` (what `npx auth secret`
  now prints). If sign-in 500s, a missing/mismatched `AUTH_SECRET` is the first
  suspect.
- **Three services for the full app:** uvicorn :8000 (from `backend/`, venv
  active), Postgres (`docker compose up -d` from repo root — service name is
  `postgres`, user/db/password all `portfoliopilot`), `npm run dev` :3000.
- **Schema changes: no Alembic.** `hashed_password` was added via
  `ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password VARCHAR;` to
  preserve memory/history/checkpoints. New columns on existing tables still need
  a manual ALTER.
- **Reseeding a password:** generate in the venv
  (`bcrypt.hashpw(b'pw', bcrypt.gensalt()).decode()`), then seed via a heredoc
  (`docker compose exec -T postgres psql … <<SQL … SQL`) so Git Bash doesn't
  mangle the `$` in the hash. Verify with
  `SELECT left(hashed_password,7), length(hashed_password)` → `$2b$12$`, `60`.
- **Hooks placement:** `useUserId()` (and any hook) must be the first lines
  inside the component body. A hook at module scope throws "Invalid hook call /
  Cannot read properties of null (reading 'useContext')" — seen once in dev
  when the call landed above the function.
- **The backend is currently unguarded** — see the V9 deferred item. This is
  intentional scope for V8, not an oversight; it's the first thing V9 closes.

---

## V8 git history

```
feat(v8): add credential verification endpoint
feat(v8): configure NextAuth v5 with a Credentials provider
feat(v8): add login page, session provider, and route protection
feat(v8): derive user_id from the session, not a hardcoded constant
feat(v8): add sign-out button and user email to the dashboard nav
docs(v8): add V8 implementation brief
(tag) v8
```

To reconstruct the V8 baseline at any point: `git checkout v8`.
