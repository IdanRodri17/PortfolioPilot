# PortfolioPilot V7 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Captures what was built across V7
> (V7a delivery data layer, V7b channel layer, V7c orchestration, V7d frontend
> settings), what deviated from the V7 design doc, and what was explicitly
> deferred — so any subsequent Claude conversation picks up with full context.

**Status:** Shipped. Tagged `v7` on `main`. Pushed to
`github.com/IdanRodri17/PortfolioPilot`.

**Smoke tests passed:**

- **V7a schema:** `telegram_chat_id VARCHAR` column added to `users` via
  surgical `ALTER TABLE` (no data loss); `delivery_preferences` table
  auto-provisioned by lifespan `create_all`. `GET /api/delivery-preferences/idan_demo`
  returns `{ preference: null }` before first save.
- **V7a CRUD:** `PUT` with daily/08:00/Asia-Jerusalem/both-channels saves and
  round-trips via `GET`; missing-address gate returns 422 when `deliver_telegram`
  is true but `telegram_chat_id` is null.
- **V7b renderers:** `render_telegram_brief` produces a sub-4096-char HTML
  brief; `render_email_html` renders a styled full report. Both verified against
  a live `idan_demo` report pulled from `/api/reports/history`.
- **V7b Telegram sender:** brief delivered to `996382157` (Idan19025 bot);
  `send_telegram_message` normalises the Bot API's `ok: false` 200-envelope
  into `TelegramSendError`.
- **V7b connect flow:** `POST /api/telegram/connect/idan_demo` reads
  `getUpdates` and binds `chat_id = 996382157`; subsequent `GET` shows
  `telegram_connected: true`.
- **V7b email sender:** designed report email delivered to `idan101012@gmail.com`
  via Resend; `send_email` normalises a missing key, transport errors, and Resend
  4xx bodies into `EmailSendError`.
- **V7c run-now:** `POST /api/deliveries/run-now/idan_demo` → 200
  `{ channels: { telegram: "sent", email: "sent" } }`; report appears in
  `/api/reports/history`; memory count unchanged (read-only memory confirmed).
- **V7c due check:** `POST /api/run-due-deliveries` returns `due: 0` when
  `last_sent_at` is current; returns `due: 1` and delivers after nulling
  `last_sent_at`; a second immediate call returns `due: 0` (dedupe holds).
- **V7c scheduler:** APScheduler tick boots with log line
  `"Delivery scheduler started: dispatch_due now, then every N min"`;
  with `DUE_CHECK_INTERVAL_MINUTES=1` and `last_sent_at=NULL`, both channels
  deliver automatically within ~1 minute without any curl.
- **V7d settings page:** `/settings` loads saved preference; channels, cadence,
  time, and timezone controls round-trip; Connect Telegram button flips
  `telegram_connected` in-place; Save shows `✓ Settings saved`; Send Now
  triggers a delivery and prints the per-channel result.

---

## What was built

### V7a — Delivery data layer

```
backend/
├── app/
│   ├── db/models.py          # + telegram_chat_id column on User;
│   │                         #   + DeliveryPreference model (1:1 w/ User)
│   ├── schemas/
│   │   └── delivery.py       # NEW: DeliveryPreferenceRequest / Response
│   │                         #   (validators: ≥1 channel, cadence params,
│   │                         #    valid IANA zone via ZoneInfo)
│   └── api/
│       └── delivery.py       # NEW: GET + PUT /api/delivery-preferences/{user_id}
│                             #   (address gate: email→User.email,
│                             #    telegram→telegram_chat_id)
└── requirements.txt          # + tzdata (Windows zoneinfo needs it)
```

`DeliveryPreference` stores eleven fields: `deliver_telegram`, `deliver_email`,
`cadence` ("daily" | "every_n_days" | "weekly"), `interval_days`, `weekday`
(0 = Mon … 6 = Sun), `send_time_local` (SQLAlchemy `Time`), `timezone` (IANA
string), `enabled`, `last_sent_at` (timestamptz), `updated_at`. The Time +
IANA-string split is the key design decision: resolving the zone per-date
means "08:00 local" is always correct across Israeli DST.

`telegram_chat_id` did not exist on `User` — the design doc was wrong that it
was "reserved." Applied via `ALTER TABLE users ADD COLUMN telegram_chat_id
VARCHAR` to preserve accumulated memory/history/checkpoints.

### V7b — Channel layer

```
backend/app/
├── delivery/
│   ├── __init__.py           # NEW (package)
│   └── renderers.py          # NEW: render_email_html + render_telegram_brief
│                             #   over FinalReport dict; pure functions, no creds
├── tools/
│   ├── telegram_sender.py    # NEW: send_telegram_message + get_updates
│   │                         #   (Bot API wrapper, pattern #4)
│   └── email_sender.py       # NEW: send_email via Resend HTTP API
│                             #   (pattern #4, Authorization: Bearer header)
└── api/
    └── telegram.py           # NEW: POST /api/telegram/connect/{user_id}
                              #   (one-shot getUpdates bind, no webhook/long-poll)
```

Email uses **Resend** (httpx POST to `api.resend.com/emails`). Free tier sends
only from `onboarding@resend.dev` and only to the account email until a domain
is verified — fine for a single-user demo. Telegram uses **parse_mode="HTML"**
(not MarkdownV2, to avoid escaping numbers/tickers).

"Top move" in the brief is deterministic: the recommendation with the largest
absolute `target_change_pct`. One graph run → one `FinalReport` → rendered to
both channels (run-once render-down, pattern #48).

### V7c — Orchestration

```
backend/app/
├── delivery/
│   └── dispatcher.py         # NEW: deliver_for_user + DeliveryError
│                             #   + _is_due + dispatch_due
├── api/
│   └── deliveries.py         # NEW: POST /api/deliveries/run-now/{user_id}
│                             #   + POST /api/run-due-deliveries
├── core/config.py            # + telegram_bot_token, resend_api_key, from_email,
│                             #   public_app_base_url, due_check_interval_minutes
└── main.py                   # + AsyncIOScheduler in lifespan
                              #   (dispatch_due every N min, next_run_time=now)
```

`deliver_for_user`: reads user/portfolio/pref into plain values → closes ORM
session → runs graph once → resumes `human_review` interrupt with empty approvals
(read-only memory, pattern #49) → reuses `_persist_report` so the scheduled
report appears in `/history` → sends best-effort per channel via
`asyncio.to_thread` → stamps `last_sent_at` only if ≥1 channel succeeded.

`_is_due`: resolves the scheduled local time per-date in the user's IANA zone
(DST-correct, pattern #51); due when the period's wall-clock time has arrived
and `last_sent_at` predates it. Handles daily / every_n_days / weekly cadences.
A bad timezone disables that user from the batch (logged) without crashing it.

`AsyncIOScheduler` is started in the lifespan (not at import) because it binds
to the running event loop — same constraint as the async checkpointer. The tick
is intentionally dumb (every N minutes); all cadence/DST/dedupe logic lives in
`dispatch_due`, so an over-frequent tick can never double-send (pattern #50).

### V7d — Settings frontend

```
frontend/src/
├── lib/
│   ├── types.ts              # + Cadence, DeliveryPreference,
│   │                         #   DeliveryPreferencesView, DeliveryPreferenceInput
│   └── api.ts                # + getDeliveryPreferences, putDeliveryPreferences,
│                             #   connectTelegram
└── app/
    ├── page.tsx              # + "· Settings" link in inline nav row
    └── settings/
        └── page.tsx          # NEW: channel toggles (gated on email_set /
                              #   telegram_connected), cadence + time + timezone,
                              #   Connect Telegram button, Save, Send Now
```

The `send_time_local` stored as `"HH:MM:SS"` is stripped to `"HH:MM"` for
`<input type="time">` on load; Pydantic parses either form on PUT. The timezone
field is a curated select of 13 IANA zones (full picker deferred).

---

## Deviations from the V7 design doc

| Area | Design doc | V7 actually does | Why |
|---|---|---|---|
| `telegram_chat_id` | "Already reserved on User" | **Not present — surgical `ALTER TABLE` required** | V2 brief explicitly deferred it. `create_all` silently skips existing tables; ALTER preserves accumulated memory/history/checkpoints. |
| Unattended `human_review` interrupt | Not specified | **Resume with empty approvals** (read-only memory) | Scheduled runs have no human to approve. Empty-approval resume reaches END cleanly; memory is read (personalisation) but never written without the HITL gate. |
| Trigger mechanism | External cron suggested | **In-process APScheduler** + endpoint as alternative | Simpler for a local demo (one fewer service); the `POST /api/run-due-deliveries` endpoint makes an external cron a drop-in replacement with zero logic changes. |
| First tick timing | Not specified | **`next_run_time=datetime.now()`** (immediate on boot) | Makes restarting the server a natural re-check; avoids a full interval wait to confirm the scheduler is working. |
| Email provider | Not specified | **Resend** (httpx, no SDK) | Clean DX, free tier covers the demo, one less dependency. |
| Timezone select | Full IANA picker implied | **Curated 13-zone list** | YAGNI for a single-user demo; full picker deferred. |

---

## Explicitly deferred (build in noted version)

- **V8 — NextAuth.js auth** (replaces hardcoded `idan_demo`); all
  `user_id`/namespace keys are already auth-ready.
- **Full IANA timezone picker** — a searchable combobox of all ~600 IANA zones;
  the current curated select is sufficient for the demo.
- **User profile page** — editing `User.email` in the UI; currently set
  directly via psql.
- **Telegram `/start` linking-code flow** — the production UX for multi-user;
  the one-shot `getUpdates` bind works for a single demo user.
- **Telegram long-poll reconnect on 409** — if `getUpdates` fails because no
  message was found, the UI tells the user to message the bot first; no retry
  loop is implemented.
- **Email domain verification** — until a domain is verified, Resend limits
  sends to the account email from `onboarding@resend.dev`; fine for the demo.
- **Per-channel last_sent_at** — currently one timestamp per user; a
  channel-level stamp would allow Telegram and email to retry independently
  after a partial failure.

---

## Patterns established — load-bearing for V8+

48. **Run-once render-down:** one graph run produces one `FinalReport`, rendered
    to all enabled channels. The graph is never run twice because there are two
    channels — the render functions are pure and cheap.

49. **Read-only memory for unattended runs:** scheduled/triggered deliveries
    resume the `human_review` interrupt with `approved_indices: []`. The report
    is personalised (memory_loader reads the store) but no new memories are
    written without a human in the loop. Every scheduled thread reaches END
    cleanly with no orphaned checkpoint.

50. **Dumb tick + smart due check:** the APScheduler interval job calls
    `dispatch_due()` on a fixed cadence; all cadence arithmetic, DST handling,
    and `last_sent_at` dedupe live in the dispatcher. An over-frequent tick can
    never double-send, and swapping the in-process scheduler for an external cron
    hitting `POST /api/run-due-deliveries` requires zero logic changes.

51. **IANA zone + wall-clock Time split:** the `timezone` column stores the IANA
    zone name; `send_time_local` stores a wall-clock `Time`. `_is_due` resolves
    the zone per-date so "08:00 Asia/Jerusalem" is always the correct UTC instant
    across DST transitions — never a frozen offset.

*(Patterns #1–#47 from V1–V6 remain in force.)*

---

## Environment notes for the next Claude

- **Three services up:** `uvicorn` on :8000 (from `backend/`, venv active),
  Postgres (`docker compose up -d` from repo root), `npm run dev` on :3000
  (from `frontend/`).
- **APScheduler boots immediately** (`next_run_time=now`). Every uvicorn restart
  runs a due-check straight away; `last_sent_at` dedupe prevents double-sends
  within a period.
- **`DUE_CHECK_INTERVAL_MINUTES`** defaults to 10. Set to 1 in `.env` to demo
  the automatic tick; set back to 10 after.
- **Resend free tier** sends from `onboarding@resend.dev` to your account email
  only. A 403 from `send_email` means the recipient doesn't match the Resend
  account email. Verify a domain in the Resend dashboard to lift both limits.
- **Telegram connect** requires the user to have messaged the bot recently
  (within ~24 h). `getUpdates` reads unconfirmed updates and is idempotent.
  A 409 on the connect endpoint means no updates were found.
- **`GUARDRAIL_FORCE_FAIL=1`** forces a guardrail retry on every graph run —
  don't export it in the uvicorn shell.
- **Benign warning:** `Deserializing unregistered type … FinalReport from
  checkpoint` — output unaffected; see V6 brief for the fix.
- **Schema changes:** no Alembic. New tables auto-create via `create_all`;
  new columns on existing tables need `ALTER TABLE`.

---

## V7 git history

```
feat(v7): add delivery data model (telegram_chat_id + DeliveryPreference)
feat(v7): add delivery preference schemas and CRUD endpoints
feat(v7): add email and telegram report renderers
feat(v7): add Telegram Bot API sender
feat(v7): add Telegram connect endpoint
feat(v7): add Resend email sender
feat(v7): add delivery dispatcher and run-now trigger
feat(v7): add timezone-aware due check and run-due-deliveries
feat(v7): run due deliveries on an in-process APScheduler tick
feat(v7): add delivery-preferences API client and types
feat(v7): add delivery settings page with channel and schedule controls
docs(v7): add V7 implementation brief
(tag) v7
```

To reconstruct the V7 baseline at any point: `git checkout v7`.
