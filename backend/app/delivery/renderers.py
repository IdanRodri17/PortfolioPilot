"""
Pure renderers: one validated FinalReport, rendered down to each channel (V7).

Run-once, render-down (V7 design decision #3): the graph produces ONE
FinalReport; these functions render that single result two ways — a full HTML
email and a short Telegram brief — so the two channels can never contradict
each other. No LLM calls, no I/O: pure field-selection + formatting over the
report dict. That purity is why they live in app/delivery/ rather than in a
node or a tool — they are trivially unit-testable with a literal report.

Input shape: the FinalReport as a dict (schemas/report.py -> model_dump), which
is exactly what report_complete carries and what Report.raw_result stores.
Accepting the dict (not the Pydantic class) keeps these decoupled from the model
and testable without constructing one.

Telegram format note: the brief is built for parse_mode="HTML" (set by the
sender in the next step), NOT MarkdownV2. MarkdownV2 requires escaping a long
list of characters ( . - ! ( ) etc.) that appear constantly in numbers and
tickers; one missed escape is a 400 from the Bot API. Telegram's HTML subset
(<b>, <i>, <a>, <code>) only needs &, <, > escaped — far safer for dynamic
financial text. html.escape handles exactly those three.

Versioning:
    V7: this file (V7b).
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional

# Palette — light, refined fintech. Echoes the app's accent semantics
# (emerald = positive/increase, rose = negative/reduce, slate = neutral) but on
# a LIGHT canvas: dark-background emails render unpredictably across clients
# (forced inversions, blown-out contrast), so light is the robust, professional
# default and the brand shows through the accents, not the background.
_PAGE_BG = "#eef0f3"
_CARD_BG = "#ffffff"
_BORDER = "#e6e8eb"
_INK = "#0f172a"  # slate-900, primary text
_MUTED = "#64748b"  # slate-500, secondary text
_FAINT = "#94a3b8"  # slate-400, tertiary
_EMERALD = "#059669"
_EMERALD_BG = "#ecfdf5"
_ROSE = "#e11d48"
_ROSE_BG = "#fff1f2"
_SLATE_BG = "#f1f5f9"
_SLATE_INK = "#475569"

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


# ─── small formatters ─────────────────────────────────────────────────


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _usd(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "$—"


def _pct(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{'+' if v > 0 else ''}{v:.2f}%"


def _sentiment_counts(insights: list[dict]) -> str:
    pos = sum(1 for i in insights if i.get("sentiment") == "Positive")
    neu = sum(1 for i in insights if i.get("sentiment") == "Neutral")
    neg = sum(1 for i in insights if i.get("sentiment") == "Negative")
    return f"{pos} positive · {neu} neutral · {neg} negative"


def _top_recommendation(recs: list[dict]) -> Optional[dict]:
    """The single most impactful move: largest |target_change_pct|. None if the
    list is empty (composition already within profile)."""
    if not recs:
        return None
    return max(recs, key=lambda r: abs(r.get("target_change_pct", 0) or 0))


# ─── Telegram brief (parse_mode="HTML") ───────────────────────────────


def render_telegram_brief(report: dict, base_url: str) -> str:
    """Short glance for Telegram: value + 24h move, the single top move, the
    sentiment lean, and a link back. Short by construction — orders of magnitude
    under the Bot API's 4096-char limit. Returns text for parse_mode='HTML'."""
    val = report.get("portfolio_valuation", {}) or {}
    total = val.get("total_usd")
    change = val.get("change_24h_percent", 0) or 0
    arrow = "▲" if change >= 0 else "▼"

    lines = [
        "<b>PortfolioPilot</b> — your portfolio brief",
        "",
        f"<b>{_esc(_usd(total))}</b>  {arrow} {_esc(_pct(change))} <i>(24h)</i>",
    ]

    top = _top_recommendation(report.get("rebalancing_recommendations", []) or [])
    if top is None:
        lines.append("Top move: <b>none</b> — composition is within your risk profile.")
    else:
        action = str(top.get("action", "")).capitalize()
        asset = _esc(top.get("asset", ""))
        chg = _esc(_pct(top.get("target_change_pct", 0)))
        lines.append(f"Top move: <b>{_esc(action)} {asset}</b> ({chg})")

    lines.append(
        f"Sentiment: {_esc(_sentiment_counts(report.get('market_insights', []) or []))}"
    )
    lines.append("")
    lines.append(f'<a href="{_esc(base_url)}/history">View the full report →</a>')
    return "\n".join(lines)


# ─── Threshold alerts (V18) ───────────────────────────────────────────


def render_alert_telegram(messages: list[str], base_url: str) -> str:
    """A short alert brief for Telegram (parse_mode='HTML'). One or more
    triggered conditions as bullet lines, plus a link back. Pure formatting."""
    title = (
        "<b>PortfolioPilot</b> — alert"
        if len(messages) == 1
        else f"<b>PortfolioPilot</b> — {len(messages)} alerts"
    )
    lines = [title, ""]
    lines += [f"• {_esc(m)}" for m in messages]
    lines += ["", f'<a href="{_esc(base_url)}/history">Open PortfolioPilot →</a>']
    return "\n".join(lines)


def render_alert_email(messages: list[str], base_url: str) -> str:
    """A compact HTML alert email — same light palette/shell language as the full
    report email, trimmed to a heading + one card per triggered condition."""
    heading = (
        "Portfolio alert"
        if len(messages) == 1
        else f"{len(messages)} portfolio alerts"
    )
    cards = "".join(
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border:1px solid {_BORDER};border-radius:10px;margin:0 0 10px;">'
        f'<tr><td style="padding:14px 16px;font-size:14px;line-height:1.55;color:{_INK};">'
        f"{_esc(m)}</td></tr></table>"
        for m in messages
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>PortfolioPilot alert</title>
</head>
<body style="margin:0;padding:0;background:{_PAGE_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_PAGE_BG};padding:28px 12px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%;background:{_CARD_BG};border:1px solid {_BORDER};border-radius:16px;overflow:hidden;font-family:{_FONT};">
      <tr><td style="padding:24px 28px;border-bottom:1px solid {_BORDER};">
        <span style="font-size:17px;font-weight:700;letter-spacing:-.01em;color:{_INK};">Portfolio<span style="color:{_EMERALD};">Pilot</span></span>
      </td></tr>
      <tr><td style="padding:24px 28px 8px;">
        {_section_heading(heading)}
        {cards}
      </td></tr>
      <tr><td style="padding:8px 28px 28px;">
        <table role="presentation" cellpadding="0" cellspacing="0"><tr>
          <td style="background:{_EMERALD};border-radius:10px;">
            <a href="{_esc(base_url)}/history" style="display:inline-block;padding:12px 22px;font-family:{_FONT};font-size:14px;font-weight:600;color:#ffffff;text-decoration:none;">Open PortfolioPilot →</a>
          </td>
        </tr></table>
      </td></tr>
      <tr><td style="padding:18px 28px;border-top:1px solid {_BORDER};background:#fafbfc;">
        <p style="margin:0;font-size:12px;line-height:1.5;color:{_FAINT};">
          You're getting this because you enabled threshold alerts.
          <a href="{_esc(base_url)}/settings" style="color:{_MUTED};">Manage alerts</a>.
        </p>
        <p style="margin:8px 0 0;font-size:11px;color:{_FAINT};">Informational only — not financial advice.</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


# ─── What-changed digest (V23) ────────────────────────────────────────


def render_change_digest_telegram(digest: dict, base_url: str) -> str:
    """Compact 'what changed since your last report' brief for Telegram (HTML)."""
    lines = ["<b>PortfolioPilot</b> — what changed", ""]
    if digest.get("value_delta_pct") is not None:
        up = (digest.get("value_delta_usd") or 0) >= 0
        since = f" since {digest['prev_date']}" if digest.get("prev_date") else ""
        lines.append(
            f"Portfolio{_esc(since)}: {'▲' if up else '▼'} "
            f"{_esc(_pct(digest['value_delta_pct']))} "
            f"({_esc(_usd(digest['value_delta_usd']))}) → "
            f"<b>{_esc(_usd(digest['total_usd']))}</b>"
        )
    else:
        lines.append(f"Portfolio value: <b>{_esc(_usd(digest['total_usd']))}</b>")

    movers = digest.get("movers") or []
    if movers:
        text = ", ".join(
            f"{_esc(m['symbol'])} {_esc(_pct(m['change_24h_percent']))}"
            for m in movers[:3]
        )
        lines.append(f"Movers (24h): {text}")

    tn = digest.get("top_now")
    if tn:
        tp = digest.get("top_prev")
        if tp and tp.get("symbol") == tn["symbol"]:
            lines.append(
                f"Top holding: {_esc(tn['symbol'])} {tn['pct']}% "
                f"<i>(was {tp['pct']}%)</i>"
            )
        else:
            lines.append(f"Top holding: {_esc(tn['symbol'])} {tn['pct']}%")

    if not digest.get("notable"):
        lines += ["", "<i>A quiet day — nothing major moved.</i>"]
    lines += ["", f'<a href="{_esc(base_url)}/">Open the full report →</a>']
    return "\n".join(lines)


def render_change_digest_email(digest: dict, base_url: str) -> str:
    """Compact 'what changed' HTML email — same light shell as the report email."""
    up = (digest.get("value_delta_usd") or 0) >= 0
    if digest.get("value_delta_pct") is not None:
        delta_color = _EMERALD if up else _ROSE
        delta_html = (
            f'<p style="margin:6px 0 0;font-size:15px;font-weight:600;color:{delta_color};">'
            f'{"▲" if up else "▼"} {_esc(_pct(digest["value_delta_pct"]))} '
            f'<span style="color:{_FAINT};font-weight:400;">'
            f'({_esc(_usd(digest["value_delta_usd"]))} since {_esc(digest.get("prev_date") or "last report")})</span></p>'
        )
    else:
        delta_html = ""

    mover_rows = "".join(
        f'<tr><td style="padding:6px 0;font-family:{_MONO};font-size:13px;color:{_INK};">{_esc(m["symbol"])}</td>'
        f'<td align="right" style="padding:6px 0;font-family:{_MONO};font-size:13px;'
        f'color:{_EMERALD if m["change_24h_percent"] >= 0 else _ROSE};">'
        f'{_esc(_pct(m["change_24h_percent"]))}</td></tr>'
        for m in (digest.get("movers") or [])[:5]
    )
    movers_html = (
        f'{_section_heading("Biggest movers (24h)")}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{mover_rows}</table>'
        if mover_rows
        else ""
    )

    tn = digest.get("top_now")
    top_html = ""
    if tn:
        tp = digest.get("top_prev")
        was = (
            f" (was {tp['pct']}%)" if tp and tp.get("symbol") == tn["symbol"] else ""
        )
        top_html = (
            f'<p style="margin:14px 0 0;font-size:13px;color:{_MUTED};">'
            f'Top holding: <span style="font-family:{_MONO};color:{_INK};">{_esc(tn["symbol"])}</span> '
            f'{tn["pct"]}%{_esc(was)}.</p>'
        )

    quiet_html = (
        f'<p style="margin:14px 0 0;font-size:13px;color:{_FAINT};font-style:italic;">'
        f'A quiet day — nothing major moved.</p>'
        if not digest.get("notable")
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>PortfolioPilot — what changed</title>
</head>
<body style="margin:0;padding:0;background:{_PAGE_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_PAGE_BG};padding:28px 12px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%;background:{_CARD_BG};border:1px solid {_BORDER};border-radius:16px;overflow:hidden;font-family:{_FONT};">
      <tr><td style="padding:24px 28px;border-bottom:1px solid {_BORDER};">
        <span style="font-size:17px;font-weight:700;letter-spacing:-.01em;color:{_INK};">Portfolio<span style="color:{_EMERALD};">Pilot</span></span>
        <span style="float:right;font-size:12px;color:{_FAINT};">what changed</span>
      </td></tr>
      <tr><td style="padding:24px 28px 8px;">
        <p style="margin:0;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{_FAINT};">Portfolio value</p>
        <p style="margin:8px 0 0;font-size:30px;font-weight:700;letter-spacing:-.02em;color:{_INK};">{_esc(_usd(digest["total_usd"]))}</p>
        {delta_html}
        {top_html}
        {quiet_html}
      </td></tr>
      <tr><td style="padding:12px 28px 8px;">{movers_html}</td></tr>
      <tr><td style="padding:8px 28px 28px;">
        <table role="presentation" cellpadding="0" cellspacing="0"><tr>
          <td style="background:{_EMERALD};border-radius:10px;">
            <a href="{_esc(base_url)}/" style="display:inline-block;padding:12px 22px;font-family:{_FONT};font-size:14px;font-weight:600;color:#ffffff;text-decoration:none;">Open the full report →</a>
          </td>
        </tr></table>
      </td></tr>
      <tr><td style="padding:18px 28px;border-top:1px solid {_BORDER};background:#fafbfc;">
        <p style="margin:0;font-size:11px;color:{_FAINT};">A quick deltas-only update. <a href="{_esc(base_url)}/settings" style="color:{_MUTED};">Manage delivery</a> · not financial advice.</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


# ─── Email HTML (full report) ─────────────────────────────────────────


def _insight_card(i: dict) -> str:
    sent = i.get("sentiment", "Neutral")
    if sent == "Positive":
        bg, ink = _EMERALD_BG, _EMERALD
    elif sent == "Negative":
        bg, ink = _ROSE_BG, _ROSE
    else:
        bg, ink = _SLATE_BG, _SLATE_INK
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_BORDER};border-radius:10px;margin:0 0 10px;">
        <tr><td style="padding:14px 16px;">
          <span style="font-family:{_MONO};font-size:12px;font-weight:600;color:{_INK};background:{_SLATE_BG};border-radius:5px;padding:3px 7px;">{_esc(i.get("asset",""))}</span>
          <span style="font-size:11px;font-weight:600;color:{ink};background:{bg};border-radius:999px;padding:3px 10px;margin-left:8px;">{_esc(sent)}</span>
          <p style="margin:10px 0 0;font-size:13px;line-height:1.55;color:{_MUTED};">{_esc(i.get("summary",""))}</p>
        </td></tr>
      </table>"""


def _recommendation_row(r: dict) -> str:
    action = str(r.get("action", "hold")).lower()
    if action == "reduce":
        ink, label, arrow = _ROSE, "Reduce", "↓"
    elif action == "increase":
        ink, label, arrow = _EMERALD, "Increase", "↑"
    else:
        ink, label, arrow = _SLATE_INK, "Hold", "→"
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_BORDER};border-radius:10px;margin:0 0 10px;">
        <tr>
          <td width="34" valign="top" style="padding:14px 0 14px 16px;font-family:{_MONO};font-size:16px;font-weight:700;color:{ink};">{arrow}</td>
          <td style="padding:14px 16px 14px 6px;">
            <p style="margin:0;font-size:13px;color:{_INK};">
              <span style="font-weight:700;color:{ink};">{label}</span>
              <span style="font-family:{_MONO};color:{_INK};">{_esc(r.get("asset",""))}</span>
              <span style="color:{_FAINT};">({_esc(_pct(r.get("target_change_pct",0)))})</span>
            </p>
            <p style="margin:6px 0 0;font-size:13px;line-height:1.55;color:{_MUTED};">{_esc(r.get("rationale",""))}</p>
          </td>
        </tr>
      </table>"""


def _section_heading(text: str) -> str:
    return (
        f'<p style="margin:0 0 12px;font-size:11px;font-weight:700;letter-spacing:.08em;'
        f'text-transform:uppercase;color:{_FAINT};">{_esc(text)}</p>'
    )


def render_email_html(
    report: dict, base_url: str, generated_at: Optional[datetime] = None
) -> str:
    """Render the full FinalReport as a self-contained HTML email document.

    Structure mirrors the app's FinalReportView (valuation hero, market
    insights, recommendations, narrative) so the email and the web report read
    as the same artifact. Inline styles + a centered table shell for
    cross-client robustness; a hidden preheader sets the inbox preview line.
    """
    when = generated_at or datetime.now(timezone.utc)
    date_str = when.strftime("%B %d, %Y")

    val = report.get("portfolio_valuation", {}) or {}
    total = val.get("total_usd")
    change = val.get("change_24h_percent", 0) or 0
    up = change >= 0
    chg_color = _EMERALD if up else _ROSE
    arrow = "▲" if up else "▼"

    confidence = report.get("confidence", 0) or 0
    conf_label = (
        "High" if confidence >= 0.7 else "Moderate" if confidence >= 0.5 else "Low"
    )
    conf_pct = round(confidence * 100)

    insights = sorted(
        report.get("market_insights", []) or [], key=lambda i: i.get("asset", "")
    )
    insights_html = "".join(_insight_card(i) for i in insights) or (
        f'<p style="margin:0;font-size:13px;color:{_MUTED};">No market insights available.</p>'
    )

    recs = report.get("rebalancing_recommendations", []) or []
    if recs:
        recs_html = "".join(_recommendation_row(r) for r in recs)
    else:
        recs_html = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{_EMERALD_BG};border-radius:10px;"><tr><td style="padding:14px 16px;'
            f'font-size:13px;color:{_EMERALD};">No changes needed — your composition is within '
            f'your risk profile.</td></tr></table>'
        )

    paragraphs = [
        p.strip()
        for p in (report.get("summary_narrative", "") or "").split("\n\n")
        if p.strip()
    ]
    narrative_html = "".join(
        f'<p style="margin:0 0 12px;font-size:14px;line-height:1.65;color:{_SLATE_INK};">{_esc(p)}</p>'
        for p in paragraphs
    )

    preheader = (
        f"{_usd(total)} {arrow} {_pct(change)} today · "
        f"{len(recs)} recommendation(s) · confidence {conf_label.lower()}"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>PortfolioPilot report</title>
</head>
<body style="margin:0;padding:0;background:{_PAGE_BG};">
<span style="display:none;max-height:0;overflow:hidden;opacity:0;color:{_PAGE_BG};">{_esc(preheader)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_PAGE_BG};padding:28px 12px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%;background:{_CARD_BG};border:1px solid {_BORDER};border-radius:16px;overflow:hidden;font-family:{_FONT};">

      <!-- Header -->
      <tr><td style="padding:24px 28px;border-bottom:1px solid {_BORDER};">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="font-size:17px;font-weight:700;letter-spacing:-.01em;color:{_INK};">
            Portfolio<span style="color:{_EMERALD};">Pilot</span>
          </td>
          <td align="right" style="font-size:12px;color:{_FAINT};">{_esc(date_str)}</td>
        </tr></table>
      </td></tr>

      <!-- Valuation hero -->
      <tr><td style="padding:28px;">
        <p style="margin:0;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{_FAINT};">Portfolio value</p>
        <p style="margin:8px 0 0;font-size:38px;font-weight:700;letter-spacing:-.02em;color:{_INK};">{_esc(_usd(total))}</p>
        <p style="margin:6px 0 0;font-size:14px;font-weight:600;color:{chg_color};">{arrow} {_esc(_pct(change))} <span style="color:{_FAINT};font-weight:400;">in the last 24h</span></p>
        <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:18px;"><tr>
          <td style="font-size:12px;color:{_MUTED};padding-right:10px;">Confidence · {_esc(conf_label)}</td>
          <td width="120"><table role="presentation" width="120" cellpadding="0" cellspacing="0"><tr>
            <td style="height:6px;background:{_SLATE_BG};border-radius:999px;">
              <table role="presentation" width="{max(0, min(100, conf_pct))}%" cellpadding="0" cellspacing="0"><tr>
                <td style="height:6px;background:{_EMERALD};border-radius:999px;font-size:0;line-height:0;">&nbsp;</td>
              </tr></table>
            </td>
          </tr></table></td>
          <td style="font-family:{_MONO};font-size:12px;color:{_MUTED};padding-left:10px;">{conf_pct}%</td>
        </tr></table>
      </td></tr>

      <!-- Market insights -->
      <tr><td style="padding:4px 28px 8px;">
        {_section_heading("Market insights")}
        {insights_html}
      </td></tr>

      <!-- Recommendations -->
      <tr><td style="padding:12px 28px 8px;">
        {_section_heading("Rebalancing recommendations")}
        {recs_html}
      </td></tr>

      <!-- Narrative -->
      <tr><td style="padding:16px 28px 8px;">
        {_section_heading("Summary")}
        {narrative_html}
      </td></tr>

      <!-- CTA -->
      <tr><td style="padding:14px 28px 28px;">
        <table role="presentation" cellpadding="0" cellspacing="0"><tr>
          <td style="background:{_EMERALD};border-radius:10px;">
            <a href="{_esc(base_url)}/history" style="display:inline-block;padding:12px 22px;font-family:{_FONT};font-size:14px;font-weight:600;color:#ffffff;text-decoration:none;">View the full report →</a>
          </td>
        </tr></table>
      </td></tr>

      <!-- Footer -->
      <tr><td style="padding:18px 28px;border-top:1px solid {_BORDER};background:#fafbfc;">
        <p style="margin:0;font-size:12px;line-height:1.5;color:{_FAINT};">
          This report was delivered automatically by PortfolioPilot.
          <a href="{_esc(base_url)}/settings" style="color:{_MUTED};">Manage delivery preferences</a>.
        </p>
        <p style="margin:8px 0 0;font-size:11px;color:{_FAINT};">Informational only — not financial advice.</p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
