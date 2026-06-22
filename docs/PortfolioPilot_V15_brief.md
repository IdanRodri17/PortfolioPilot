# PortfolioPilot V15 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md` and `PortfolioPilot_Upgrades_BuildSpec.md`.
> Captures V15 (V15a guest/demo mode, V15b shareable report + PDF) — the
> publishing wave: zero-signup trial and free distribution, built on V9's
> default-closed baseline.

**Status:** Shipped. Tagged `v15` on `main`. Confirmed live in the browser: the
guest `/demo` generates a real report, a `/r/{id}` share link renders read-only
logged-out, and Export-PDF produces a clean light, report-only document.

**Headline:** the app is now publishable. A visitor can try a real report at
`/demo` with no signup, and any report can be shared as a public read-only link
at `/r/{id}` (or saved as a PDF) — all without weakening V9: the backend stays
default-closed and these routes are *explicit* exceptions.

**Smoke tests — verified in the build session (live, no LLM):**

- **V15a:** `/demo` → 200 logged-out (no redirect to /login);
  `GET /api/portfolio/idan_demo` with no token → 200; any other user → 401; a
  non-demo `generate-report` with no token → 401 (before any LLM call).
- **V15b:** `/r/{id}` → 200 logged-out; the capability payload
  `GET /api/reports/{id}` → 200. `user_id` confirmed to be the slug `idan_demo`,
  not the email (email lives only in the users table, never joined into the
  report) — no PII to strip.
- **Frontend:** `tsc` + `eslint` clean.

**Smoke tests — confirmed live (browser):**

- **Demo:** incognito → `/demo` → holdings load, **Generate report** streams a
  real report (donut, concentration, diff, advice), no edit/chat/memory/settings.
- **Share:** generate a report while logged in → **Share** copies a `/r/{id}`
  link → open it in a private window → renders read-only (no chat/edit). **Export
  PDF** produces a clean single-document PDF (toolbar/banners hidden).

---

## What was built

### V15a — guest / demo mode

```
backend/app/api/{deps,portfolio,generate}.py   # require_owner_or_demo; optional generate token
frontend/src/
├── app/demo/page.tsx        # NEW public read-only dashboard bound to idan_demo
├── middleware.ts            # allowlist /demo (+ /api/token, which self-guards)
├── lib/api.ts               # authHeaders() -> {} when there's no session
└── lib/useReportStream.ts   # generate SSE omits the token when there's no session
```

With V9 default-closed, V15a opens *exactly* the demo user's reads + generate:
`require_owner_or_demo` makes `idan_demo` publicly readable (others still need a
matching token), and `generate-report`'s token becomes optional with an
`idan_demo`-only bypass (every other user is still checked before any LLM call).
The `/demo` page reuses the dashboard components with the authenticated-only
affordances omitted (no edit/chat/memory/settings/sign-out) plus a sign-up
banner.

### V15b — shareable report + PDF

```
frontend/src/
├── app/r/[reportId]/page.tsx   # NEW public read-only shared report
├── components/FinalReportView.tsx  # no-print Share + Export PDF toolbar
├── app/globals.css             # @media print (hide .no-print, keep styling)
└── middleware.ts               # allowlist /r/*
```

`/r/{id}` is a client page that fetches the uuid4 capability URL (the read
endpoint V9 deliberately left open) and renders `FinalReportView` without a
reportId — so the chat stays hidden; it's read + Export-PDF only. "Share" copies
the `/r/{id}` link; "Export PDF" is `window.print()` against a `@media print`
stylesheet (zero dependencies).

---

## Deviations from the upgrade spec

| Area | Spec | V15 actually does | Why |
|---|---|---|---|
| Demo chat | (unspecified) | **disabled** in /demo (no reportId passed) | ask costs an LLM call and is owner-gated; keep the guest path read+generate only |
| Demo interrupt | "auto-decline/hide the memory modal" | the demo just **doesn't render** the modal; the report arrives before the interrupt, the graph is left paused (harmless, nothing saved) | resume is auth-gated; not worth a carve-out for a guest |
| PDF styling | "clean Save-as-PDF" | a **light** print theme (slate→ink overrides via substring class selectors) that prints the **report only** — app chrome hidden via `.no-print` on each page | a dark screen-dump prints poorly; the light restyle is cheap and yields a real-looking document |
| PII strip | "strip if the payload carries email/PII" | **no strip needed** — `user_id` is the slug `idan_demo`, not the email | confirmed against the users table; revisit if signup ever sets id = email |
| `v15` tag | tag on ship | deferred until the live browser test | "no tag without a passing end-to-end check" |

---

## Explicitly deferred

- **Push the `v15` tag.** Created locally after the live smoke test passed;
  `git push origin v15` (and `--tags`) to publish.
- **Per-report share token.** Today the uuid4 id *is* the capability. A separate
  revocable `share_token` (and an opt-in "make public" toggle) would be stricter
  privacy than capability-by-id.
- **Demo paused-graph cleanup.** Each demo generate leaves a paused checkpoint
  (memory step). Harmless, but a janitor (or a demo-only graph without the HITL
  branch) would keep the checkpointer tidy.
- **Pixel-perfect / branded PDF.** A client print-to-canvas lib if the
  browser-print output ever needs exact branding.

---

## Patterns established

78. **Default-closed + explicit opt-out.** V9 locks everything; "public" is then
    an auditable exception (`require_owner_or_demo`, the demo generate bypass, the
    capability read), not an oversight. The safest order: lock first, open
    deliberately.

79. **Guest-resilient client auth.** `authHeaders()` returns `{}` and the SSE
    `start()` omits the token when there's no session, so the same components and
    helpers serve both authenticated and guest contexts — the backend decides.

80. **One report component, many contexts via optional props.** `FinalReportView`
    serves the dashboard (diff/advice/chat/share), history (chat/share), demo
    (no chat), and public `/r` (read-only) purely by which optional props are
    passed.

81. **Capability-URL sharing + zero-dep PDF.** The unguessable uuid4 is the share
    token; the public page is a thin client renderer of the already-open read
    endpoint, and PDF is `@media print` + `.no-print` (no library).

*(Patterns #1–#77 from V1–V14 + V9 remain in force.)*

---

## Environment notes for the next Claude

- **Public routes:** `/demo`, `/r/*` (frontend, via the middleware matcher) and
  `GET /api/reports/{id}`, `GET /api/portfolio/idan_demo`, demo `generate-report`
  (backend). Everything else is owner-gated (V9).
- **`/api/token` is allowlisted in middleware but self-guards** (401 without a
  session) — so the guest demo gets a clean 401 instead of a redirect, and
  `authHeaders()` falls back to `{}`.
- **Demo writes are NOT open** — editing, memory wipe, delivery, settings, and
  chat all still require the owner token. Verified: a logged-out write → 401.
- **Restart the frontend after adding routes** (`/demo`, `/r/[reportId]`) —
  Turbopack picks up new route files on restart, not always via hot reload.

---

## V15 git history

```
feat(v15a): open a read-only demo path for the guest user
feat(v15a): read-only guest demo dashboard
feat(v15b): public shareable report page with PDF export
docs(v15): add V15 implementation brief
fix(v15b): light-themed, report-only PDF export
(tag) v15
```

To reconstruct the V15 baseline at any point: `git checkout v15`.
