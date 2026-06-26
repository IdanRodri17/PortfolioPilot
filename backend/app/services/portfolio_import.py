"""
Portfolio import — deterministic CSV parsing + shared symbol resolution (V26).

This module is the *pure core* of the import feature: no FastAPI, no DB, and no
LLM. CSV parsing is plain string work (fits the suite's zero-I/O test
convention); the only outside touch is `validate_holdings`, which calls
`lookup_symbol` — and that's injectable (`lookup_fn`) precisely so tests run
without the network.

Both import modes (CSV here, free-text in `nl_import`) converge on the same
intermediate row dict — ``{input_symbol, symbol, quantity, cost_basis, line}``
— and then flow through `validate_holdings`, so validity is decided once, by
real market data, never by the parser or the LLM.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Callable, List, Optional, Tuple

from app.schemas.import_portfolio import PreviewRow, RowError
from app.tools.stock_data import StockDataError, lookup_symbol

# A review screen with hundreds of rows is unusable, and each row costs one
# (cached) price lookup — so cap the batch. Extras surface as a RowError.
MAX_HOLDINGS = 100

# First-cell values that mark a broker-export summary/footer row, not a holding.
_FOOTER_FIRST_CELLS = {
    "total",
    "totals",
    "grand total",
    "subtotal",
    "cash",
    "cash & cash investments",
    "account total",
    "account",
}


def _match_column(header: str) -> Optional[str]:
    """Map one CSV header cell to a role: 'symbol', 'quantity', or 'cost'.

    Deliberately conservative on cost: a bare/last/market "price" is NOT treated
    as a buy price. Cost basis is optional, so missing it (user can add it in the
    preview) is far better than importing today's market price AS the buy price,
    which would silently corrupt P/L.
    """
    h = header.strip().lower()
    if not h:
        return None
    if "symbol" in h or "ticker" in h or "security" in h or "instrument" in h or h == "sym":
        return "symbol"
    if (
        "quantity" in h
        or "shares" in h
        or "units" in h
        or "position" in h
        or h in ("qty", "amount", "# of shares", "no. of shares", "no of shares")
    ):
        return "quantity"
    # A dollar TOTAL (e.g. "Cost Basis Total", "Total Cost", "Market Value") is
    # not a per-unit buy price — excluding it avoids importing a total as a
    # per-share cost, which would corrupt P/L the same way a bare "price" would.
    if "total" in h or "value" in h or "market" in h:
        return None
    if (
        "cost" in h
        or "paid" in h
        or "purchase price" in h
        or "buy price" in h
        or "avg price" in h
        or "average price" in h
        or "unit cost" in h
    ):
        return "cost"
    return None


def _header_colmap(cells: List[str]) -> Optional[dict]:
    """Build {role: column_index} from a candidate header row. Returns None when
    the row doesn't name a symbol column (so it's treated as positional data)."""
    colmap: dict = {}
    for idx, cell in enumerate(cells):
        role = _match_column(cell)
        if role and role not in colmap:
            colmap[role] = idx
    return colmap if "symbol" in colmap else None


def _cell(cells: List[str], idx: Optional[int]) -> Optional[str]:
    if idx is None or idx < 0 or idx >= len(cells):
        return None
    return cells[idx]


def _clean_number(raw: Optional[str]) -> Optional[float]:
    """Parse a possibly-messy numeric cell into a float, or None.

    Handles currency symbols ($, ₪, €), thousands separators, stray percent
    signs, and the US-vs-EU decimal ambiguity:
      "$1,234.50" -> 1234.5   "1.234,56" -> 1234.56   "1,5" -> 1.5   "10" -> 10.0
    A lone comma group of exactly 3 digits ("1,234") is read as thousands.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None

    # Accounting-style negatives: "(150.00)" or a trailing/leading minus. We track
    # the sign and parse the magnitude, so a negative quantity/cost surfaces as
    # such (-> needs_quantity / blocked at save) instead of a plausible positive.
    neg = (
        (s.startswith("(") and s.endswith(")"))
        or s.lstrip().startswith("-")
        or s.rstrip().endswith("-")
    )

    t = re.sub(r"[^0-9,.]", "", s)  # drop currency/%, parens, and any sign
    if not t or t in {".", ","}:
        return None

    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            # comma is the decimal separator (EU): "1.234,56"
            t = t.replace(".", "").replace(",", ".")
        else:
            # dot is the decimal separator (US): "1,234.56"
            t = t.replace(",", "")
    elif "," in t:
        parts = t.split(",")
        if len(parts) > 2:
            t = t.replace(",", "")  # "1,234,567" -> thousands
        elif len(parts[1]) == 3 and parts[0] not in ("", "0"):
            t = t.replace(",", "")  # "1,234" -> thousands (but "0,123" is decimal)
        else:
            t = t.replace(",", ".")  # "1,5" / "1,50" / "0,123" -> decimal

    try:
        val = float(t)
    except ValueError:
        return None
    return -val if neg else val


def parse_csv(content: str) -> Tuple[List[dict], List[RowError], List[str]]:
    """Parse a CSV blob into intermediate holding dicts.

    Returns (rows, errors, warnings). A row with a symbol but no readable
    quantity still emits (quantity=None) so the preview can flag it — one bad
    cell never 422s the whole batch. A row with no symbol becomes a RowError so
    nothing is dropped silently.
    """
    rows: List[dict] = []
    errors: List[RowError] = []
    warnings: List[str] = []

    # Strip a leading UTF-8 BOM (common in Excel/Windows exports) so it can't
    # corrupt the first symbol on the no-header path. file.text() decodes UTF-8
    # but doesn't strip the BOM, and str.strip() leaves U+FEFF intact.
    text = content.lstrip("﻿").strip("\n")
    if not text.strip():
        return rows, errors, warnings

    sample = "\n".join(text.splitlines()[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # default to comma

    reader = csv.reader(io.StringIO(text), dialect)
    records = [
        (i + 1, cells)
        for i, cells in enumerate(reader)
        if any(c.strip() for c in cells)  # skip blank lines
    ]
    if not records:
        return rows, errors, warnings

    _, first_cells = records[0]
    colmap = _header_colmap(first_cells)
    if colmap is not None:
        data = records[1:]
    else:
        colmap = {"symbol": 0, "quantity": 1, "cost": 2}
        data = records
        warnings.append(
            "No header row detected — assumed columns are: symbol, quantity, cost."
        )

    for line, cells in data:
        first = cells[0].strip().lower() if cells else ""
        if first in _FOOTER_FIRST_CELLS:
            continue  # broker summary/footer line, not a holding
        input_symbol = (_cell(cells, colmap.get("symbol")) or "").strip()
        symbol = input_symbol.upper()
        if not symbol:
            errors.append(
                RowError(
                    line=line,
                    raw=dialect.delimiter.join(cells),
                    reason="No symbol found in this row.",
                )
            )
            continue
        rows.append(
            {
                "input_symbol": input_symbol,
                "symbol": symbol,
                "quantity": _clean_number(_cell(cells, colmap.get("quantity"))),
                "cost_basis": _clean_number(_cell(cells, colmap.get("cost"))),
                "line": line,
            }
        )
    return rows, errors, warnings


def normalize_rows(rows: List[dict]) -> Tuple[List[dict], List[RowError], bool]:
    """Uppercase/trim symbols and cap the batch at MAX_HOLDINGS.

    Returns (rows, errors, truncated). Duplicate detection happens later in
    `validate_holdings` (it needs first-seen order), not here.
    """
    out: List[dict] = []
    for r in rows:
        r = dict(r)
        r["symbol"] = (r.get("symbol") or "").strip().upper()
        out.append(r)

    errors: List[RowError] = []
    truncated = False
    if len(out) > MAX_HOLDINGS:
        extra = len(out) - MAX_HOLDINGS
        out = out[:MAX_HOLDINGS]
        truncated = True
        errors.append(
            RowError(
                line=None,
                raw="",
                reason=(
                    f"Import is limited to {MAX_HOLDINGS} holdings; "
                    f"{extra} extra row(s) were skipped."
                ),
            )
        )
    return out, errors, truncated


def validate_holdings(
    rows: List[dict],
    lookup_fn: Callable[[str], Optional[dict]] = lookup_symbol,
) -> List[PreviewRow]:
    """Resolve each intermediate row against live market data into a PreviewRow.

    The status mirrors the manual editor's rule set so the preview feels native:
      - ok            : ticker found (name/price/currency attached)
      - unknown       : ticker not found -> the UI blocks save for that row
      - unverified    : provider error -> the UI soft-warns, save still allowed
      - needs_quantity: missing/non-positive quantity (still looked up for name)
      - duplicate     : symbol already listed above

    Currency comes ONLY from the validated lookup (USD; ILS for .TA via the
    existing agorot->ILS normalization; USD for crypto) — never inferred. The
    cost_basis number is echoed unchanged in the symbol's native currency.
    `lookup_fn` is injectable so tests never touch the network.
    """
    seen: set = set()
    out: List[PreviewRow] = []
    for r in rows:
        symbol = r["symbol"]
        input_symbol = r.get("input_symbol") or symbol
        quantity = r.get("quantity")
        cost_basis = r.get("cost_basis")
        line = r.get("line")

        if symbol in seen:
            out.append(
                PreviewRow(
                    symbol=symbol,
                    input_symbol=input_symbol,
                    quantity=quantity,
                    cost_basis=cost_basis,
                    status="duplicate",
                    note="Already listed above — edit the first row instead.",
                    line=line,
                )
            )
            continue
        seen.add(symbol)

        name = price = currency = None
        look = "ok"
        try:
            hit = lookup_fn(symbol)
            if hit:
                name = hit.get("name")
                price = hit.get("price")
                currency = hit.get("currency")
            else:
                look = "unknown"
        except StockDataError:
            look = "unverified"

        if quantity is None or quantity <= 0:
            status = "needs_quantity"
            note = "Enter a quantity for this holding."
        elif look == "ok":
            status, note = "ok", None
        elif look == "unknown":
            status = "unknown"
            note = "We couldn't find that ticker — edit or remove it."
        else:
            status = "unverified"
            note = "Couldn't verify right now — you can still save."

        out.append(
            PreviewRow(
                symbol=symbol,
                input_symbol=input_symbol,
                quantity=quantity,
                cost_basis=cost_basis,
                status=status,
                name=name,
                price=price,
                currency=currency,
                note=note,
                line=line,
            )
        )
    return out
