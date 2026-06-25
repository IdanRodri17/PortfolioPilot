# PortfolioPilot V23 — Implementation Brief

> `docs/REVIEW.md` V23 (the keystone): make the scheduled digest *signal, not
> repetition*. A daily sender used to get 7 near-identical full reports a week.

**Status:** Shipped (backend verified live + unit-tested; frontend tsc + eslint clean).
Tag `v23` pending the live browser check. Code on `main`.

**Headline:** a delivery preference can now be **"What's changed"** instead of the full
report — a lightweight, deterministic digest of what moved since the last report
(portfolio value delta, the day's biggest movers, top-holding drift), sent via the same
Telegram/email channels. **No graph run, no LLM** — cheap and fast.

---

## What was built

```
backend/app/
├── db/models.py + db/light_migrations.py   # DeliveryPreference.digest_mode ("full"|"changes_only")
├── schemas/delivery.py + api/delivery.py    # round-trip digest_mode; GET /api/digest/preview/{id}
├── delivery/change_digest.py  # NEW: compute_change_digest() — pure deltas vs the last report
├── delivery/renderers.py      # render_change_digest_{telegram,email}
└── delivery/dispatcher.py     # branch: changes_only -> cheap digest (no graph); else full report

frontend/src/
├── lib/types.ts + lib/api.ts  # DigestMode, ChangeDigest, DigestPreview; previewDigest()
└── app/settings/page.tsx      # "What to send" picker (Full report / What's changed) + live preview
```

### How it works
- **`digest_mode` on the preference** (default `"full"`, additive light-migration — existing
  users unchanged). Settings has a two-option "What to send" picker.
- **`compute_change_digest`** is pure + deterministic: current prices vs the user's last
  archived report → value Δ ($ and %), biggest 24h movers, top-holding now vs then, and a
  **`notable`** flag so a quiet day says so instead of faking signal.
- **Dispatcher branch:** for `changes_only` with a prior report, it fetches current prices,
  computes the digest, renders, and sends — **skipping the whole graph/LLM**. The first-ever
  delivery (no baseline) falls through to a full report. `last_sent_at` stamped as usual.
- **Sentiment flips need the LLM**, so they stay in the full report; the digest links to it.
- **Preview:** `GET /api/digest/preview/{id}` dry-runs the digest (no send) — powers the
  settings "Preview what's changed" button.

---

## Smoke test
- **Verified (backend, live):** migration added `digest_mode`; preview endpoint auth-gated;
  the digest computed on the real demo portfolio renders cleanly (value Δ, movers, top
  holding, notable). New unit test `test_change_digest.py` (value delta, quiet-day, mover
  sort) — **25 tests pass**.
- **Pending (browser):** `/settings` → "What to send" → pick **What's changed** → **Preview
  what's changed** shows live deltas; Save persists the choice.

---

## Patterns established
94. **Decouple delivery cadence from report generation.** A scheduled send doesn't have to
    re-run the pipeline — a deterministic deltas-only digest is cheaper and more useful for a
    frequent sender. Reuse the channels + dedupe; branch on a `digest_mode`.

*(Patterns #1–#93 from V1–V22 remain in force.)*

---

## V23 git history
```
feat(v23): "what changed" digest mode (deltas-only scheduled send)
docs(v23): add V23 implementation brief
(tag) v23 — pending live browser check
```
