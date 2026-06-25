"""What-changed-since-last-report digest (V23).

The full scheduled report re-runs the whole LangGraph every period — for a daily
sender that's seven near-identical reports a week (noise, not signal). This
computes a lightweight, DETERMINISTIC "what changed" digest instead: current
prices vs the user's last archived report — portfolio value delta, the day's
biggest movers, and any top-holding (concentration) drift. No graph, no LLM, so
it's cheap and fast. Sentiment flips need the LLM, so those stay in the full
report (the digest links to it).

Pure compute: `compute_change_digest` takes already-fetched inputs and returns a
JSON-ready dict; the dispatcher gathers inputs + sends, the renderer formats it.
"""


def compute_change_digest(
    *,
    holdings: dict[str, float],
    prev_report: dict,
    prev_generated_at,
    market: dict[str, dict],
) -> dict:
    """Deterministic deltas of the current portfolio vs the last report.

    Returns {prev_date, total_usd, value_delta_usd, value_delta_pct, movers,
    top_now, top_prev, notable}. `notable` is False on a quiet day (nothing moved
    meaningfully) so the renderer can say so instead of forcing fake signal.
    """
    values = {
        sym: holdings[sym] * market[sym]["price"]
        for sym in holdings
        if sym in market and market[sym].get("price")
    }
    total_now = sum(values.values())

    prev_total = (prev_report.get("portfolio_valuation") or {}).get("total_usd")
    value_delta_usd = value_delta_pct = None
    if prev_total:  # truthy => non-zero, safe to divide
        value_delta_usd = round(total_now - prev_total, 2)
        value_delta_pct = round((total_now - prev_total) / prev_total * 100, 2)

    # Biggest 24h movers (up or down), largest first.
    movers = sorted(
        (
            {
                "symbol": sym,
                "change_24h_percent": round(
                    market[sym].get("change_24h_percent") or 0.0, 2
                ),
                "value_usd": round(values[sym], 2),
            }
            for sym in values
        ),
        key=lambda m: abs(m["change_24h_percent"]),
        reverse=True,
    )[:4]

    # Top holding now vs in the previous report (concentration drift).
    top_now = None
    if total_now > 0:
        sym = max(values, key=values.get)
        top_now = {"symbol": sym, "pct": round(values[sym] / total_now * 100, 1)}

    prev_comp = prev_report.get("portfolio_composition") or []
    top_prev = None
    if prev_comp:
        tp = max(prev_comp, key=lambda a: a.get("pct", 0) or 0)
        top_prev = {"symbol": tp.get("asset"), "pct": round(tp.get("pct", 0) or 0, 1)}

    notable = bool(
        (value_delta_pct is not None and abs(value_delta_pct) >= 0.5)
        or any(abs(m["change_24h_percent"]) >= 3 for m in movers)
        or (top_now and top_prev and top_now["symbol"] != top_prev["symbol"])
    )

    return {
        "prev_date": prev_generated_at.date().isoformat() if prev_generated_at else None,
        "total_usd": round(total_now, 2),
        "value_delta_usd": value_delta_usd,
        "value_delta_pct": value_delta_pct,
        "movers": movers,
        "top_now": top_now,
        "top_prev": top_prev,
        "notable": notable,
    }
