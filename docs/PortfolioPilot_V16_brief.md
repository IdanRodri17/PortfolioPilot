# PortfolioPilot V16 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md` and `PortfolioPilot_Upgrades_BuildSpec.md`.
> Captures the V16 stretch item that was picked up: crypto holdings (CoinGecko)
> + Israeli-market context. This completes the entire V9–V16 upgrade wave.

**Status:** Shipped. Tagged `v16` on `main`. Confirmed live: crypto pricing + the
activated crypto cap, agorot-aware **₪** display for TASE in the editor,
fractional share quantities, and correct **USD aggregation** for a mixed ILS+USD
portfolio (a ₪9,595 TEVA holding now contributes ~$3,200, not "$9,595").

**Headline:** the app now prices **crypto** (BTC, ETH, …) via CoinGecko
alongside stocks, activates the long-dormant `max_crypto_pct` risk check, and
adds **Israeli-market context** (TASE holdings + a configurable Bank of Israel
rate) to the report — the personal differentiator for an Israeli investor.

**Smoke tests — verified in the build session:**

- **Live CoinGecko:** `fetch_crypto_data("BTC")` returned a real USD price +
  24h change.
- **Offline:** `is_crypto`/`is_tase` detectors; `fetch_crypto_data` shape +
  unknown-coin error (httpx mocked); crypto-aware `lookup_symbol` (editor
  accepts BTC); the `max_crypto_pct` violation fires over-cap and stays silent
  under-cap; `data_ingestion` routes crypto→CoinGecko, stocks→yfinance; the
  Israeli-context block renders/omits correctly and the prompt template composes.
- **Compile/import** clean across all touched modules.

**Smoke tests — confirmed live (browser):**

- Add a crypto holding (e.g. `BTC`) in the editor → it validates ("Bitcoin · $…")
  → save → **Generate report**: BTC is priced and appears as a donut slice; an
  over-cap crypto weight shows a "Crypto is X% … exceeding the … cap" line.
- (Optional) set `BANK_OF_ISRAEL_RATE` and add a `.TA` holding (e.g. `TEVA.TA`),
  recreate the backend, regenerate → the narrative mentions the TASE holding +
  the rate.

---

## What was built

```
backend/app/
├── tools/stock_data.py        # CRYPTO_IDS, is_crypto, is_tase, fetch_crypto_data;
│                              #   crypto-aware lookup_symbol
├── graph/nodes/data_ingestion.py  # dispatch crypto->CoinGecko, else->yfinance
├── graph/nodes/risk_agent.py  # activate the max_crypto_pct violation check
├── graph/nodes/synthesizer.py # Israeli-market context block (TASE + BoI rate)
├── core/config.py             # optional bank_of_israel_rate
└── .env.example               # document BANK_OF_ISRAEL_RATE
```

**Crypto.** A curated `CRYPTO_IDS` map (ticker → CoinGecko id) drives detection
and pricing — `fetch_crypto_data` hits CoinGecko's free `/simple/price` (httpx,
no key) and returns the *same* `{price, change_24h_percent}` shape as stocks, so
`data_ingestion`, `risk_agent`, the composition donut, and the report are all
provider-agnostic. `risk_agent` now sums crypto value share and flags it against
each profile's `max_crypto_pct` — the check the threshold was defined for back in
V3.

**Israeli context.** `synthesizer` injects a context block when the portfolio has
TASE (`.TA`) holdings and/or `BANK_OF_ISRAEL_RATE` is configured, and the
narrative weaves it in. Off by default (empty block → silent).

---

## Deviations / decisions

| Area | Choice | Why |
|---|---|---|
| Crypto symbol→id | a **curated map** (BTC→bitcoin, …) | CoinGecko prices by id and tickers are ambiguous across coins; a map is reliable + extensible vs. a fuzzy `/coins/list` lookup |
| TASE | per-share price shown in **₪** (editor); portfolio values **converted to USD** (live `ILS=X` FX) | Yahoo quotes TASE in agorot ('ILA' = 1/100 ₪). The editor shows the native ₪ price; for the portfolio, values are converted agorot→ILS→USD so a mixed ILS+USD total and its percentages are correct (single base currency). The FX rate is cached per process with a fallback. |
| Bank of Israel rate | a **config value** woven into the narrative | a reliable knob beats scraping an obscure API; it's contextual prose, not a deterministic report field |
| Frontend | **none** | crypto flows through the existing report UI once priced; validation picks it up via the backend lookup |
| `v16` tag | deferred | pending the live browser check |

---

## Explicitly deferred

- *(Done — V16 confirmed, tagged, and pushed; the V9–V16 wave is complete.)*
- **Broader FX.** TASE→USD conversion now lands (live `ILS=X`); remaining: other
  non-USD markets, an FX-aware 24h change, and a user-selectable base currency
  (e.g. an all-Israeli portfolio shown entirely in ₪).
- **The other V16 stretch items:** threshold alerts on the delivery scheduler;
  streaming the report narrative.
- **Crypto price caching / batching.** `fetch_crypto_data` is one call per coin;
  a batched `/simple/price?ids=a,b,c` (CoinGecko supports it) would cut calls.
- **Crypto sector.** `get_sector` returns "Uncategorized" for crypto; the macro
  agent could bucket crypto as its own "sector".

---

## Patterns established

82. **Provider dispatch behind one shape.** `is_crypto` routes pricing to
    CoinGecko vs yfinance, but both return `{price, change_24h_percent}`, so
    every downstream consumer (ingestion, risk, composition, report) is
    provider-agnostic. A curated ticker→id map sidesteps ambiguous lookups.

83. **Define the threshold now, wire the detector later.** `max_crypto_pct` sat
    in `RISK_PROFILES` since V3; V16 added only the `is_crypto` detector to
    activate it — no schema or config change. Pre-wiring paid off exactly as the
    V3 comment predicted.

84. **Config-gated optional context.** The Israeli block is an empty string
    unless TASE holdings exist or the rate is set, so the feature is
    off-by-default and never fabricates a number.

*(Patterns #1–#81 from V1–V15 remain in force.)*

---

## Environment notes for the next Claude

- **CoinGecko** is free and keyless but rate-limits; a failed fetch degrades to
  the existing per-asset skip (the symbol is omitted, the report flags the gap).
- **`CRYPTO_IDS` is the allow-list** — add a ticker→id entry to support a new
  coin. Anything not in it is treated as a stock (yfinance).
- **`BANK_OF_ISRAEL_RATE`** is optional; in Docker it's a backend env var, so
  set it in `backend/.env` (or the compose env) and **recreate** the backend
  container to pick it up. Unset → the Israeli line simply doesn't appear.
- **`httpx`** was already a dependency — no new package, no image rebuild needed.

---

## V16 git history

```
feat(v16): crypto holdings via CoinGecko + activate the crypto cap
feat(v16): Israeli-market context (Bank of Israel rate + TASE)
docs(v16): add V16 implementation brief
feat(v16): show TASE holdings in ILS (agorot-aware) + accept fractional shares
docs(v16): note the ILS-display + fractional-share additions
fix(v16): convert TASE values to USD so mixed-currency totals are correct
docs(v16): record the TASE->USD FX conversion
docs(v16): mark V16 shipped
(tag) v16
```

**Post-review additions** (after live testing):
- The editor shows TASE **per-share prices in ₪** (agorot-aware) via a
  `formatMoney` helper.
- **Fractional share quantities** in the editor (decimal + comma-tolerant; the
  backend already stored floats).
- TASE portfolio values are **converted to USD** (live `ILS=X` rate) so a
  mixed-currency total and its percentages are correct — a real ₪9,595 TEVA
  holding now contributes ~$3,200, not "$9,595".

To reconstruct the V16 baseline at any point: `git checkout v16`.
With V16, the entire V9–V16 upgrade wave is shipped.
