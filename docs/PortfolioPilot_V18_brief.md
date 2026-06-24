# PortfolioPilot V18 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Threshold alerts: opt-in,
> condition-based pushes that complement the V7 scheduled digest.

**Status:** Shipped (backend verified live; frontend `tsc` + `eslint` clean). The
`v18` tag is **pending the live browser check** (configure a rule on `/settings`
and hit "Preview alerts now"). Code on `main`.

**Headline:** the app is now **proactive**, not just periodic. Instead of only a
report on a schedule, you get pinged the moment something happens — a holding
spikes/tanks, the whole portfolio swings, or one position grows too large. You
compose your own alert set: every rule is **off by default** and individually
switchable with its own threshold, so nothing arrives that you didn't ask for.

---

## What was built

```
backend/app/
├── db/
│   ├── models.py            # DeliveryPreference + 6 alert columns
│   └── light_migrations.py  # NEW: idempotent ADD COLUMN IF NOT EXISTS (existing DBs)
├── delivery/
│   ├── alerts.py            # NEW: rule engine + evaluator + scheduler entrypoint
│   └── renderers.py         # render_alert_telegram / render_alert_email
├── schemas/delivery.py      # alert fields + validation on the prefs request/response
├── api/delivery.py          # round-trip alert fields; GET /api/alerts/preview/{id}
└── main.py                  # run migrations after create_all; 2nd scheduler job

frontend/src/
├── lib/types.ts             # alert fields on the preference + AlertPreview
├── lib/api.ts               # previewAlerts()
└── app/settings/page.tsx    # "Threshold alerts" section: toggle + rules + preview
```

### The three rules (all deterministic, no LLM)

| Rule | Fires when | Dedupe key | Default |
|---|---|---|---|
| Price move | any holding's \|24h move\| ≥ X% | `price:<symbol>` | 5% |
| Portfolio move | value-weighted \|24h move\| ≥ X% | `portfolio:move` | 5% |
| Concentration | any holding's weight ≥ X% | `conc:<symbol>` | 40% |

### Why this design

- **No graph run.** Alerts are a pure price check (the same crypto/stock/TASE
  routing `data_ingestion` uses), so they're cheap enough to evaluate on every
  scheduler tick. Running the full LLM report every few minutes per user would be
  slow and costly; a price lookup is neither.
- **Per-rule cooldown.** A fired rule stamps its key into
  `DeliveryPreference.alert_state` (JSONB) and won't re-fire for
  `alert_cooldown_hours` (default 12) — mirroring how the dispatcher's
  `last_sent_at` keeps the digest idempotent within a period. A frequent tick, or
  a price hovering just past the line, never spams.
- **Opt-in everywhere.** `alerts_enabled` is the master switch (separate from the
  digest's `enabled`); each rule is live only when its threshold is non-NULL.
- **Reuse, not rebuild.** Same scheduler, same Telegram/email senders, same
  `DeliveryPreference` row, same session discipline (read → release → fetch/send →
  reopen to stamp) as the V7 dispatcher.
- **Preview = the cooldown's escape hatch for testing.** `dry_run` evaluates the
  rules against live prices and returns what *would* fire, ignoring the master
  switch and the cooldown, and never sends — so the "Preview alerts now" button
  always shows the current truth.

---

## Smoke tests

- **Verified (backend, live):**
  - migration columns present on `delivery_preferences`;
  - rule engine correct on a unit portfolio (BTC 85.7% concentration, portfolio
    +6.59% weighted) **and** on the live demo portfolio — a sub-threshold AAPL
    move (−0.91% vs a 1% rule) and a sub-threshold weighted portfolio move
    (−0.73%) are both correctly **excluded**;
  - cooldown helper suppresses a key fired within the window;
  - `GET /api/alerts/preview/{id}` registered and auth-gated (401 without a token).
- **Pending (browser):** on `/settings`, switch on **Threshold alerts**, tick a
  rule (e.g. price move ≥ 1%), **Save**, then **Preview alerts now** → see the
  live lines that would fire; raise the threshold past every move and preview
  again → "Nothing would fire". With a channel connected, a real breach is
  delivered once, then suppressed for the cooldown window.

---

## Deviations / decisions

| Area | Choice | Why |
|---|---|---|
| Migration | idempotent `ADD COLUMN IF NOT EXISTS` per statement | `create_all` never alters existing tables; no Alembic for purely-additive columns |
| Alert currency | USD (percentages are currency-agnostic) | keeps V18 focused; a ₪ option can follow the V17 toggle later |
| Sentiment-flip alert | deferred to a later phase | needs an LLM / last-report comparison — breaks the "cheap, no-LLM" property |
| Preview vs form | preview reads **saved** rules | the endpoint reads the DB; the UI hints "save first" |
| `v18` tag | deferred | pending the live browser check |

---

## Patterns established

86. **Condition-based vs schedule-based delivery.** Alerts ride the existing
    scheduler tick but are a separate, *cheap, no-LLM* check — never a graph run —
    with their own per-rule cooldown dedupe. Reuse the channels + session
    discipline; don't duplicate the dispatcher.
87. **Additive light migrations.** For columns `create_all` can't add to existing
    tables, run idempotent `ADD COLUMN IF NOT EXISTS` (one transaction each) at
    boot. Only ever additive/backward-compatible — anything else needs real
    migrations.

*(Patterns #1–#85 from V1–V17 remain in force.)*

---

## V18 git history

```
feat(v18): threshold alerts — opt-in price / portfolio / concentration pushes
docs(v18): add V18 implementation brief
(tag) v18  — pending live browser check
```

To reconstruct the V18 baseline at any point once tagged: `git checkout v18`.
