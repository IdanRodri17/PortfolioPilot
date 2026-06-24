"use client";

/**
 * /portfolio — the portfolio editor page.
 *
 * In the App Router, this file's location (app/portfolio/page.tsx) defines
 * the route. It loads the current portfolio via getPortfolio, lets the user
 * edit the asset map and risk profile, and persists via upsertPortfolio
 * (the V2 POST endpoint).
 *
 * Editable model: an array of {id, symbol, quantity} rows rather than the
 * raw {symbol: quantity} map. Editing a symbol in a map means mutating a
 * key, and add/remove invites key collisions mid-edit; an array with stable
 * ids sidesteps both. We convert rows -> map (validating along the way) only
 * at save time, mirroring the backend's PortfolioRequest rules: every symbol
 * non-empty and unique, every quantity > 0.
 *
 * V10b: each symbol is validated inline against GET /api/ticker/validate on a
 * short debounce, surfacing the company name + live price, blocking save on a
 * typo, and degrading gracefully (allow save) if validation itself fails.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { getPortfolio, upsertPortfolio, validateTicker } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import type { RiskProfile } from "@/lib/types";

import { useUserId } from "@/lib/useUserId";
const RISK_PROFILES: RiskProfile[] = ["conservative", "balanced", "aggressive"];

interface Row {
  id: string;
  symbol: string;
  quantity: string; // kept as string so partial input (empty, "1.") is valid mid-edit
  buyPrice: string; // optional cost basis (native currency); "" = not tracked (V20)
}

type LoadState = "loading" | "ready" | "error";
type SaveState =
  | { status: "idle" | "saving" | "saved" }
  | { status: "error"; message: string };

// Per-symbol ticker validation status, keyed by normalized symbol.
type TickerStatus =
  | { state: "checking" }
  | { state: "valid"; name: string; price: number; currency: string }
  | { state: "invalid" }
  | { state: "error" }; // couldn't verify (network) — non-blocking

function rowsToPayload(rows: Row[]): {
  assets?: Record<string, number>;
  cost_basis?: Record<string, number>;
  error?: string;
} {
  const assets: Record<string, number> = {};
  const cost_basis: Record<string, number> = {};
  for (const r of rows) {
    const symbol = r.symbol.trim().toUpperCase();
    if (!symbol) return { error: "Every asset needs a symbol." };
    if (symbol in assets) return { error: `Duplicate symbol: ${symbol}.` };
    // Tolerate a comma decimal separator (common on Israeli/EU keyboards).
    const qty = Number(r.quantity.trim().replace(",", "."));
    if (!Number.isFinite(qty) || qty <= 0) {
      return { error: `Quantity for ${symbol} must be greater than 0.` };
    }
    assets[symbol] = qty;
    // Buy price is optional; when present it must be a positive number (V20).
    const bpRaw = r.buyPrice.trim().replace(",", ".");
    if (bpRaw) {
      const bp = Number(bpRaw);
      if (!Number.isFinite(bp) || bp <= 0) {
        return { error: `Buy price for ${symbol} must be greater than 0.` };
      }
      cost_basis[symbol] = bp;
    }
  }
  if (Object.keys(assets).length === 0) return { error: "Add at least one asset." };
  return { assets, cost_basis };
}

function TickerStatusLine({ status }: { status?: TickerStatus }) {
  if (!status) return null;
  if (status.state === "checking")
    return <p className="mt-1 pl-1 text-xs text-faint">Checking…</p>;
  if (status.state === "valid")
    return (
      <p className="mt-1 pl-1 text-xs text-forest">
        {status.name} · {formatMoney(status.price, status.currency)}
      </p>
    );
  if (status.state === "invalid")
    return (
      <p className="mt-1 pl-1 text-xs text-terracotta">Couldn’t find that ticker.</p>
    );
  // network error — couldn't verify; explicitly non-blocking
  return (
    <p className="mt-1 pl-1 text-xs text-ochre">
      Couldn’t verify right now — you can still save.
    </p>
  );
}

export default function PortfolioEditorPage() {
  const { userId } = useUserId();
  const [load, setLoad] = useState<LoadState>("loading");
  const [rows, setRows] = useState<Row[]>([]);
  const [riskProfile, setRiskProfile] = useState<RiskProfile>("balanced");
  const [save, setSave] = useState<SaveState>({ status: "idle" });
  const [validations, setValidations] = useState<Record<string, TickerStatus>>(
    {},
  );
  // Lets the debounce read the latest validations without re-arming the timer.
  // Synced in an effect (not during render) per React 19's refs rule.
  const validationsRef = useRef(validations);
  useEffect(() => {
    validationsRef.current = validations;
  }, [validations]);

  useEffect(() => {
    if (!userId) return;
    let active = true;
    getPortfolio(userId)
      .then((data) => {
        if (!active) return;
        setRows(
          Object.entries(data.assets).map(([symbol, qty]) => ({
            id: crypto.randomUUID(),
            symbol,
            quantity: String(qty),
            buyPrice:
              data.cost_basis && data.cost_basis[symbol] != null
                ? String(data.cost_basis[symbol])
                : "",
          })),
        );
        setRiskProfile(data.risk_profile);
        setLoad("ready");
      })
      .catch(() => active && setLoad("error"));
    return () => {
      active = false;
    };
  }, [userId]);

  // Distinct, normalized symbols currently in the editor. symbolsKey changes
  // only when the SET of symbols changes — not on a quantity keystroke — so
  // validation re-arms exactly when it should.
  const symbols = rows.map((r) => r.symbol.trim().toUpperCase()).filter(Boolean);
  const symbolsKey = [...new Set(symbols)].sort().join(",");

  // Debounced inline validation: 400ms after edits settle, validate any symbol
  // not yet looked up. One request per settled symbol, never per keystroke.
  useEffect(() => {
    const handle = setTimeout(() => {
      const known = validationsRef.current;
      const pending = [...new Set(symbols)].filter((s) => !(s in known));
      if (pending.length === 0) return;
      setValidations((v) => {
        const next = { ...v };
        for (const s of pending) next[s] = { state: "checking" };
        return next;
      });
      for (const sym of pending) {
        validateTicker(sym)
          .then((r) =>
            setValidations((v) => ({
              ...v,
              [sym]: r.found
                ? {
                    state: "valid",
                    name: r.name!,
                    price: r.price!,
                    currency: r.currency ?? "USD",
                  }
                : { state: "invalid" },
            })),
          )
          .catch(() =>
            // Fetch failure (not "not found") — degrade gracefully, allow save.
            setValidations((v) => ({ ...v, [sym]: { state: "error" } })),
          );
      }
    }, 400);
    return () => clearTimeout(handle);
    // symbols is read via closure; symbolsKey is the content-stable trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey]);

  // Any edit invalidates the previous save/error message.
  function touched() {
    setSave((s) => (s.status === "idle" ? s : { status: "idle" }));
  }

  function updateRow(
    id: string,
    field: "symbol" | "quantity" | "buyPrice",
    value: string,
  ) {
    setRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)),
    );
    touched();
  }

  function addRow() {
    setRows((prev) => [
      ...prev,
      { id: crypto.randomUUID(), symbol: "", quantity: "", buyPrice: "" },
    ]);
    touched();
  }

  function removeRow(id: string) {
    setRows((prev) => prev.filter((r) => r.id !== id));
    touched();
  }

  async function handleSave() {
    const { assets, cost_basis, error } = rowsToPayload(rows);
    if (error) {
      setSave({ status: "error", message: error });
      return;
    }
    setSave({ status: "saving" });
    try {
      await upsertPortfolio({
        user_id: userId!,
        assets: assets!,
        cost_basis,
        risk_profile: riskProfile,
      });
      setSave({ status: "saved" });
    } catch (e) {
      setSave({ status: "error", message: String(e) });
    }
  }

  // Block save while any present symbol is a known typo. Network "error"
  // states are intentionally NOT blocking — we degrade rather than trap.
  const hasInvalidTicker = rows.some((r) => {
    const s = r.symbol.trim().toUpperCase();
    return s !== "" && validations[s]?.state === "invalid";
  });

  return (
    <main className="min-h-screen bg-backdrop text-ink">
      <div className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
        <Link
          href="/"
          className="text-sm text-label transition-colors hover:text-ink"
        >
          ← Dashboard
        </Link>

        <h1 className="mt-3 font-serif text-3xl font-medium tracking-[-0.02em] sm:text-4xl">
          Edit portfolio
        </h1>
        <p className="mt-1 text-sm text-muted">
          Update holdings and risk profile, then save.
        </p>

        {load === "loading" && (
          <p className="mt-8 text-sm text-faint">Loading portfolio…</p>
        )}
        {load === "error" && (
          <p className="mt-8 text-sm text-terracotta">Could not load portfolio.</p>
        )}

        {load === "ready" && (
          <div className="mt-8 space-y-8">
            {/* Risk profile */}
            <section>
              <h2 className="mb-3 font-serif text-lg font-medium text-ink">
                Risk profile
              </h2>
              <div className="inline-flex flex-wrap rounded-[4px] border border-line p-1">
                {RISK_PROFILES.map((p) => (
                  <button
                    key={p}
                    onClick={() => {
                      setRiskProfile(p);
                      touched();
                    }}
                    className={`min-h-[40px] rounded-[2px] px-3 py-1.5 text-sm capitalize transition-colors ${
                      riskProfile === p
                        ? "bg-forest text-paper"
                        : "text-muted hover:text-ink"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </section>

            {/* Assets */}
            <section>
              <h2 className="mb-1 font-serif text-lg font-medium text-ink">
                Assets
              </h2>
              <p className="mb-3 text-xs text-faint">
                Quantities can be fractional. Buy price is optional — enter it in
                the currency shown for each ticker to track your gain/loss.
              </p>
              <div className="space-y-3">
                {rows.map((row) => {
                  const sym = row.symbol.trim().toUpperCase();
                  const status = sym ? validations[sym] : undefined;
                  const invalid = status?.state === "invalid";
                  return (
                    <div key={row.id}>
                      <div className="flex items-start gap-2">
                        <div className="flex flex-1 flex-wrap gap-2 sm:flex-nowrap">
                          <input
                            value={row.symbol}
                            onChange={(e) =>
                              updateRow(row.id, "symbol", e.target.value.toUpperCase())
                            }
                            placeholder="AAPL"
                            className={`min-h-[40px] w-full rounded-[3px] border bg-card px-3 py-2 font-mono text-sm text-ink placeholder:text-faint focus:outline-none sm:w-28 ${
                              invalid
                                ? "border-neg-line focus:border-terracotta"
                                : "border-field focus:border-forest"
                            }`}
                          />
                          <input
                            value={row.quantity}
                            onChange={(e) => updateRow(row.id, "quantity", e.target.value)}
                            type="text"
                            inputMode="decimal"
                            placeholder="Qty (0.5)"
                            className="min-h-[40px] min-w-0 flex-1 rounded-[3px] border border-field bg-card px-3 py-2 font-mono text-sm text-ink placeholder:text-faint focus:border-forest focus:outline-none"
                          />
                          <input
                            value={row.buyPrice}
                            onChange={(e) => updateRow(row.id, "buyPrice", e.target.value)}
                            type="text"
                            inputMode="decimal"
                            placeholder={
                              status?.state === "valid"
                                ? `Buy price (${status.currency === "ILS" ? "₪" : "$"})`
                                : "Buy price (opt)"
                            }
                            className="min-h-[40px] min-w-0 flex-1 rounded-[3px] border border-field bg-card px-3 py-2 font-mono text-sm text-ink placeholder:text-faint focus:border-forest focus:outline-none"
                          />
                        </div>
                        <button
                          onClick={() => removeRow(row.id)}
                          aria-label={`Remove ${row.symbol || "asset"}`}
                          className="min-h-[40px] shrink-0 rounded-[2px] px-2 py-2 text-faint transition-colors hover:text-terracotta"
                        >
                          ✕
                        </button>
                      </div>
                      <TickerStatusLine status={status} />
                    </div>
                  );
                })}
              </div>
              <button
                onClick={addRow}
                className="mt-3 text-sm text-forest transition-colors hover:text-forest-deep"
              >
                + Add asset
              </button>
            </section>

            {/* Save */}
            <section className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
              <button
                onClick={handleSave}
                disabled={save.status === "saving" || hasInvalidTicker}
                className="min-h-[40px] rounded-[2px] bg-forest px-4 py-2 font-medium text-paper transition-colors hover:bg-forest-deep disabled:opacity-50"
              >
                {save.status === "saving" ? "Saving…" : "Save portfolio"}
              </button>
              {save.status === "saved" && (
                <span className="text-sm text-forest">Saved.</span>
              )}
              {save.status === "error" && (
                <span className="text-sm text-terracotta">{save.message}</span>
              )}
              {hasInvalidTicker && save.status !== "error" && (
                <span className="text-sm text-terracotta">
                  Fix the invalid ticker(s) before saving.
                </span>
              )}
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
