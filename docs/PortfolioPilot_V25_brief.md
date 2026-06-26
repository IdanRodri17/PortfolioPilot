# PortfolioPilot V25 — Implementation Brief

> `docs/REVIEW.md` V25 — give people a reason to come back between reports. Until
> now the dashboard only knew what you *own*. A watchlist tracks the tickers you're
> *thinking* about.

**Status:** Shipped (backend verified live; frontend tsc + eslint clean). Tag `v25`
pending the live browser check. Code on `main`.

**Headline:** a **"Watching"** card on the dashboard — add any ticker (validated), see its
live price + 24h change, remove with one click. Read-only on the public demo.

---

## What was built

```
backend/app/
├── db/models.py              # User.watchlist JSONB (default [])
├── db/light_migrations.py    # ADD COLUMN IF NOT EXISTS watchlist on users
├── schemas/portfolio.py      # WatchlistRequest (+ normalize: upper/dedupe/cap 30)
└── api/portfolio.py          # GET /api/watchlist/{id} (live quotes) + PUT (owner-only)

frontend/src/
├── lib/types.ts              # WatchlistItem, WatchlistView
├── lib/api.ts                # getWatchlist, putWatchlist
├── components/WatchlistCard.tsx   # live quotes, add-by-ticker, remove ×, canEdit
├── app/page.tsx              # <WatchlistCard userId canEdit /> (editable)
└── app/demo/page.tsx         # <WatchlistCard userId={DEMO_USER} /> (read-only)
```

### How it works
- **Storage:** `User.watchlist` is a JSONB list of symbols — additive + backward-compatible
  (default `[]`), so old user rows need no migration beyond the idempotent `ADD COLUMN`.
- **Read (`GET /api/watchlist/{id}`):** returns the symbols plus a **live quote per symbol**
  via the same batched `fetch_trending_quotes` the trending card uses. A symbol whose quote
  can't be fetched still appears (null price/change → renders "—"), so you never lose track
  of it. Demo-readable (same gate as the portfolio).
- **Write (`PUT /api/watchlist/{id}`):** full-replace, owner-scoped (`require_user` + id
  check). The `WatchlistRequest` validator upper-cases, trims, de-dupes, and caps at 30.
- **Add flow:** the card validates the typed symbol through the existing
  `GET /api/ticker/validate` before saving — an unknown ticker shows an inline error instead
  of silently adding a dead symbol. After a save it re-reads so prices reflect the new set.
- **Demo:** `canEdit={false}` hides the add input + remove buttons but still shows the seeded
  list (idan_demo: META, AMD, COIN), with a "+ Add" link to the portfolio editor instead.

---

## Smoke test

Reload the dashboard (Turbopack HMR; hard-refresh if needed), then:

1. **Dashboard — see it.** Below the report, a **"Watching"** card. If your watchlist is
   empty it says *"Nothing yet — add a ticker below."*
2. **Add by ticker.** Type `COIN` (or any symbol) → **Add**. It should validate, then appear
   as a tile with live price + a green ▲ / red ▼ 24h change.
3. **Reject a typo.** Type `ZZZZ` → **Add**. Inline error *"Couldn't find ZZZZ"*, nothing added.
4. **Remove.** Click **Remove ×** on a tile → it disappears and the list persists on reload.
5. **Demo is read-only.** Open `/demo` → the card shows META / AMD / COIN with **no** add
   input and **no** Remove buttons (a "+ Add" link instead).
6. **Persistence.** Reload the dashboard → your edits are still there.

**Verified (backend, live):** `GET /api/watchlist/idan_demo` →
`META $542.87 −2.65% · AMD $532.57 +2.47% · COIN $142.52 −5.06%`.

---

## Patterns established
96. **Track-don't-own as a first-class list.** A watchlist is the cheapest retention hook —
    it gives the dashboard a reason to be opened daily even when the portfolio hasn't changed.
    Stored as a plain JSONB list on the user; quotes are fetched live (never persisted) so the
    card is always current and the column never goes stale.

*(Patterns #1–#95 from V1–V24 remain in force.)*

---

## V25 git history
```
feat(v25): watchlist — track tickers you don't own
docs(v25): add V25 implementation brief
(tag) v25 — pending live browser check
```
