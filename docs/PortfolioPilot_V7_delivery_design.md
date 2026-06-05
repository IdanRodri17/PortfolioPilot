# PortfolioPilot V7 — Scheduled Delivery (Design Brief, pre-development)

> Pre-development design spec for V7, in the spirit of `PortfolioPilot_SRS_dev.md` but scoped to one feature. It **supersedes the SRS §3 / §4.8 "daily digest" sketch** for everything delivery-related (see *Divergence from the SRS* below). The current build state (through V6) lives in `PortfolioPilot_V6_brief.md` — read that first for the existing code, schema, graph, and patterns #1–#47. This brief is the *what/why*; the implementing chat proposes the *how* (a step plan, approved before code), the same way V1–V6 were built.

---

## Why this version exists

PortfolioPilot's #1 value proposition is **proactive, configurable delivery**: the user decides whether to receive their analysis every morning on the commute, every few days, or weekly — without opening the app. On-demand reports already work (V1–V6); V7 makes the report come to the user. This was sketched as a V8 stretch goal in the SRS; it is being **promoted to a first-class version** because it defines the product.

Target users are **iPhone-heavy**, which rules out browser/web-push delivery (iOS only supports web push for home-screen-installed PWAs, and unreliably). Delivery is therefore **out-of-band**: Telegram and email, both of which push to the user wherever they are. The web app is the control panel (set preferences, pull reports on demand, view history/memory); delivery happens through the two channels.

V7 is fully demoable **single-user** (`idan_demo`) — it does not require auth. Auth (formerly V7) moves to V8.

---

## Locked product decisions

1. **Two channels, multi-select.** The user picks Telegram and/or Email (checkboxes; at least one). Both can be on.
2. **Channel determines format — no separate length toggle.** **Telegram = a short brief** (the glance, read at a stoplight). **Email = the full report** (the deep dive). The format follows from the channel, so there is no brief/full setting; the channel checkboxes *are* the format choice.
3. **One graph, rendered down.** Run the **existing full report graph** (V1–V6: guardrail-validated, memory-personalized) to produce one `FinalReport`. Render that single result two ways: full HTML for email, and a short brief for Telegram. **The Telegram brief is a deterministic rendering of the `FinalReport`'s fields** (valuation + 24h move + top recommendation + one-line sentiment + a "view full report" deep link) — **not a second graph, and not a second LLM call.** This guarantees the two channels never contradict each other and keeps the daily glance as trustworthy and personalized as the full report.
4. **Do NOT build the SRS's separate lightweight digest graph.** §4.8 sketched a digest graph that skips the guardrail and memory — which would make the *daily* touchpoint the *least* validated and least personalized output. That is backwards for this product. The brief is derived from the validated full report instead. (Scale caveat: a purpose-built light graph only earns its keep if a large morning batch ever proves too slow/expensive to run the full graph per user — defer it until measured, and it would slot behind the same dispatcher.)
5. **Per-user cadence + local time.** Daily, every N days, or weekly, at a chosen local time in the user's IANA timezone. "Morning" is local — do not hardcode Asia/Jerusalem.
6. **Telegram's 4096-char limit is respected by construction** — the brief is short by design; the full report goes to email (no length limit) with a deep link back to the web app surfaced in the Telegram brief.

---

## Out of scope (deferred — do NOT build in V7)

- **Interactive will-do / won't-do / already-did buttons** on delivered recommendations (Telegram inline keyboards → feed the memory store). This is the *next* version after V7 — it's where delivery and the learning value-prop fuse, and it deserves dedicated focus. V7 delivers; the intention loop comes after.
- **Crypto via CoinGecko** + `max_crypto_pct` activation (V6.5).
- **Value-weighted Recharts allocation pie** (separate V6.5).
- **Auth (NextAuth.js)** — now V8; single-user demos cover V7.
- **PWA shell, BOI prime-rate context, TASE tickers.**
- **Multi-user batch optimization / the lightweight digest graph** (scale-only; see decision #4).

---

## Data model

A new **`DeliveryPreference`** row (1:1 with user — keeps it clean and isolated from `User`):

| Field | Type | Notes |
|---|---|---|
| `user_id` | FK → users.id, unique | one preference row per user |
| `deliver_telegram` | bool | at least one channel must be true |
| `deliver_email` | bool | |
| `cadence` | `"daily" \| "every_n_days" \| "weekly"` | |
| `interval_days` | int, nullable | used when cadence = `every_n_days` |
| `weekday` | int, nullable | 0–6, used when cadence = `weekly` |
| `send_time_local` | time | e.g. 08:00 |
| `timezone` | str (IANA) | e.g. `"Asia/Jerusalem"` |
| `enabled` | bool | master on/off |
| `last_sent_at` | timestamptz, nullable | drives the due-check + dedupe |

Reuse existing columns the V2/V8 models already reserve: **`User.telegram_chat_id`** (set by the connect flow) and **`User.email`** (already nullable). **Validation rule:** a checked channel needs its address — email delivery requires `User.email`; Telegram delivery requires a linked `telegram_chat_id`. The settings UI must gate the checkboxes on this (you can't enable email with no address; ticking Telegram should drive the bot link).

---

## Components to build (the implementing chat will sequence these into sub-versions + steps)

1. **`DeliveryPreference` model + CRUD** — `GET` / `PUT /api/delivery-preferences/{user_id}` (Pydantic boundary models, per pattern #5).
2. **Connect-Telegram flow** — bind a `chat_id` to a user. A bot `/start` with a short linking code, or `POST /api/telegram/connect`. The user taps the bot once; store `telegram_chat_id`.
3. **Email sender** — a thin tool wrapper (Resend or similar) in `app/tools/`, single point of contact (pattern #4), normalizing failures into one exception. Sends the rendered HTML.
4. **Telegram sender** — a thin Bot API wrapper in `app/tools/`. Sends the brief (Markdown), short by construction.
5. **Two pure renderers over `FinalReport`** — `render_email_html(report)` (full) and `render_telegram_brief(report)` (short: valuation, 24h move, top recommendation, one-line sentiment, deep link). No LLM calls; field-selection only.
6. **Dispatcher** — a pure `dispatch_due()` (and a `deliver_for_user(user_id)`): query enabled + due preferences (timezone-aware, `last_sent_at` outside the current period), run the **compiled graph once** per due user, render + send to each selected channel (best-effort: a failed email must not block the Telegram send — log and continue, per pattern #22 spirit), then stamp `last_sent_at`.
7. **Trigger + manual endpoint** — `POST /api/deliveries/run-now/{user_id}` for testing/demo (mirrors the SRS's `digest/run-now`). For the scheduled trigger, **recommend external-cron-hits-endpoint** (`POST /api/run-due-deliveries`, hit every ~10 min by a platform cron / GitHub Actions / cron-job.org) for portability on hosts that sleep; **in-process APScheduler** is the simpler alternative *if* the deployment is always-on. The dispatch logic is identical either way — only the trigger differs. (Deploy target is still open; pick the trigger to match it.)
8. **Settings UI** — a `/settings` page (or a section on `/portfolio`): the two channel checkboxes, cadence + time + timezone, a connect-Telegram button, save. Matches the existing dark-fintech theme (pattern #29, #39).

---

## Architecture principles to carry forward (from patterns #1–#47)

- **Graph purity (pattern #7).** The dispatcher and senders live at the API/service boundary; the graph does not know delivery exists, exactly as it does not know the DB exists. The dispatcher **reuses the same compiled graph** — this is the reuse the `api/generate.py` docstring anticipated for the scheduler. No graph changes in V7.
- **Run-once, render-down.** One graph run per scheduled send; the renderers are pure functions over the channel-agnostic `FinalReport`. Never run the graph twice because two channels are checked.
- **Thin tool wrappers (pattern #4)** for the email and Telegram clients — one file each, one normalized exception each, swappable.
- **Best-effort delivery.** A failure on one channel logs and proceeds to the other; a send failure never corrupts `last_sent_at` accounting in a way that double-sends or silently drops.
- **Reuse `FinalReport`** as the payload; reuse the report-history persistence if a scheduled report should also land in `/history`.

---

## Divergence from the SRS (what this brief overrides)

- **Delivery is first-class (V7), not a V8 stretch.** The SRS ordered it last; it's the priority.
- **No separate digest graph.** §4.8's lightweight `data_ingestion → quick_sentiment_sweep → digest_formatter → telegram_sender` graph is **not built** — the brief is a rendering of the full, validated report (decision #3/#4).
- **Channel determines format**, replacing any standalone brief/full toggle.
- **Web push / PWA dropped from the delivery path** (iPhone-heavy); PWA is cosmetic and deferred.
- **Telegram-only + email-only + both** are all first-class; the SRS framed Telegram as the sole digest channel.
- The SRS's `POST /api/telegram/connect` and `digest/run-now/{user_id}` endpoints are reused conceptually.

---

## Open implementation decisions (settle in the step plan)

- **Email provider**: Resend (modern, good DX) vs Postmark vs plain SMTP; pick one, add its API key to settings/`.env`.
- **Telegram bot**: create via BotFather, store token in settings; decide the connect/linking UX (deep-link code vs manual paste).
- **Trigger**: external cron vs APScheduler — decide alongside the deploy target (still TBD).
- **Timezone**: stdlib `zoneinfo` for due computation.
- **Does a scheduled report also persist to `/history`?** (Probably yes — reuse the V5 report archive.)

---

## "Done" looks like (smoke-test shape)

Set `idan_demo`'s preferences to both channels, daily, 08:00 in a timezone; connect Telegram; hit `POST /api/deliveries/run-now/idan_demo`. Receive a **full HTML email** and a **Telegram brief of the same report**, the brief under 4096 chars and consistent with the email (same valuation, same top recommendation). Toggle to Telegram-only → only the brief arrives. Toggle to email-only → only the full email. Confirm the due/`last_sent_at` logic prevents a second send within the same period, and that a hit to `run-due-deliveries` (or the APScheduler tick) delivers to exactly the users who are due.

---

## Environment continuity (see V6 brief for detail)

Git Bash on Windows, repo root `~/Desktop/PortfolioPilot`, venv in `backend/`; run git from the repo root; activate the venv before pip/python; conventional commits (`feat(v7):`), push from the repo root, `git tag -a v7` at the end; two services up (uvicorn :8000, Postgres via `docker compose up -d`) plus the frontend dev server. **Single-line curls** when testing endpoints (multi-line `\` continuations break in Git Bash if blank lines separate them).
