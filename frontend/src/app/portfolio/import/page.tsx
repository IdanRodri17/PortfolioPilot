"use client";

/**
 * /portfolio/import — bulk import (V26).
 *
 * Two input modes (CSV paste/upload, or a free-text paste) both POST to the
 * dry-run /api/portfolio/parse, which returns a reviewable preview. The user
 * edits the rows here — reusing the editor's exact validation rules and inline
 * ticker re-check — then saves through the existing upsert, choosing to MERGE
 * into the current portfolio (default) or REPLACE it. The parse never writes;
 * this page's Save is the only write, so import can't bypass the editor's
 * save-time checks.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  parsePortfolioImport,
  getPortfolioOrNull,
  upsertPortfolio,
  validateTicker,
} from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { useUserId } from "@/lib/useUserId";
import type {
  ImportMode,
  ImportPreview,
  ImportRowStatus,
  PortfolioResponse,
  PreviewRow,
  RiskProfile,
} from "@/lib/types";

interface Row {
  id: string;
  symbol: string;
  quantity: string;
  buyPrice: string;
  inputSymbol: string; // verbatim token (e.g. "Apple") for unresolved rows
  status: ImportRowStatus; // backend's initial resolution, for the unresolved-name hint
}

type TickerStatus =
  | { state: "checking" }
  | { state: "valid"; name: string; price: number; currency: string }
  | { state: "invalid" }
  | { state: "error" };

type Stage = "input" | "preview";
type MergeMode = "merge" | "replace";

// Same rules as the editor's rowsToPayload — duplicated minimally; the backend's
// PortfolioRequest validators are the ultimate guard either way.
function rowsToPayload(rows: Row[]): {
  assets?: Record<string, number>;
  cost_basis?: Record<string, number>;
  error?: string;
} {
  const assets: Record<string, number> = {};
  const cost_basis: Record<string, number> = {};
  for (const r of rows) {
    const symbol = r.symbol.trim().toUpperCase();
    if (!symbol) return { error: "Every holding needs a symbol." };
    if (symbol in assets) return { error: `Duplicate symbol: ${symbol}.` };
    const qty = Number(r.quantity.trim().replace(",", "."));
    if (!Number.isFinite(qty) || qty <= 0) {
      return { error: `Quantity for ${symbol} must be greater than 0.` };
    }
    assets[symbol] = qty;
    const bpRaw = r.buyPrice.trim().replace(",", ".");
    if (bpRaw) {
      const bp = Number(bpRaw);
      if (!Number.isFinite(bp) || bp <= 0) {
        return { error: `Buy price for ${symbol} must be greater than 0.` };
      }
      cost_basis[symbol] = bp;
    }
  }
  if (Object.keys(assets).length === 0) return { error: "Nothing to import." };
  return { assets, cost_basis };
}

// Seed the validations map from the preview so TickerStatusLine renders without
// a refetch. needs_quantity/duplicate rows are left unset so the debounce
// re-validates them live (and the inline qty/dup hints handle the rest).
function seedValidation(row: PreviewRow): TickerStatus | undefined {
  if (row.name && row.price != null) {
    return {
      state: "valid",
      name: row.name,
      price: row.price,
      currency: row.currency ?? "USD",
    };
  }
  if (row.status === "unknown") return { state: "invalid" };
  if (row.status === "unverified") return { state: "error" };
  return undefined;
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
  return (
    <p className="mt-1 pl-1 text-xs text-ochre">
      Couldn’t verify right now — you can still save.
    </p>
  );
}

const CSV_PLACEHOLDER = "symbol,quantity,cost\nAAPL,10,150\nBTC,0.5\nTEVA.TA,100,42.5";
const TEXT_PLACEHOLDER = "10 Apple, 0.5 BTC, 1000 TEVA bought at 12";

export default function PortfolioImportPage() {
  const { userId } = useUserId();

  const [mode, setMode] = useState<ImportMode>("csv");
  const [content, setContent] = useState("");
  const [stage, setStage] = useState<Stage>("input");
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  const [rows, setRows] = useState<Row[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [validations, setValidations] = useState<Record<string, TickerStatus>>({});
  const [mergeMode, setMergeMode] = useState<MergeMode>("merge");
  const [showErrors, setShowErrors] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const validationsRef = useRef(validations);
  useEffect(() => {
    validationsRef.current = validations;
  }, [validations]);

  async function handlePreview() {
    if (!userId || !content.trim()) return;
    setParsing(true);
    setParseError(null);
    try {
      const result = await parsePortfolioImport({ user_id: userId, mode, content });
      if (result.parse_error) {
        setParseError(result.parse_error);
        setParsing(false);
        return;
      }
      const seeded: Record<string, TickerStatus> = {};
      const newRows: Row[] = result.rows.map((r) => {
        const s = seedValidation(r);
        if (s) seeded[r.symbol] = s;
        return {
          id: crypto.randomUUID(),
          symbol: r.symbol,
          quantity: r.quantity != null ? String(r.quantity) : "",
          buyPrice: r.cost_basis != null ? String(r.cost_basis) : "",
          inputSymbol: r.input_symbol,
          status: r.status,
        };
      });
      setRows(newRows);
      setValidations(seeded);
      setPreview(result);
      setStage("preview");
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "Couldn't parse that.");
    } finally {
      setParsing(false);
    }
  }

  // Same debounced inline re-validation as the editor: when a symbol the user
  // edits isn't in the validations map yet, look it up so red rows turn green.
  const symbols = rows.map((r) => r.symbol.trim().toUpperCase()).filter(Boolean);
  const symbolsKey = [...new Set(symbols)].sort().join(",");
  useEffect(() => {
    if (stage !== "preview") return;
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
            setValidations((v) => ({ ...v, [sym]: { state: "error" } })),
          );
      }
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey, stage]);

  function updateRow(id: string, field: "symbol" | "quantity" | "buyPrice", value: string) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
    setSaveError(null);
  }

  function removeRow(id: string) {
    setRows((prev) => prev.filter((r) => r.id !== id));
    setSaveError(null);
  }

  const hasInvalidTicker = rows.some((r) => {
    const s = r.symbol.trim().toUpperCase();
    return s !== "" && validations[s]?.state === "invalid";
  });

  async function handleSave() {
    if (!userId) return;
    const { assets, cost_basis, error } = rowsToPayload(rows);
    if (error) {
      setSaveError(error);
      return;
    }
    setSaving(true);
    setSaveError(null);

    // Read the current portfolio first: REPLACE preserves the risk profile,
    // MERGE also keeps existing holdings. null = a real 404 (new user) => start
    // empty. A thrown error (401/500/network) must ABORT — never fall back to
    // empty, or a full-replace merge would silently wipe existing holdings.
    let current: PortfolioResponse | null;
    try {
      current = await getPortfolioOrNull(userId);
    } catch {
      setSaveError("Couldn't read your current portfolio — please try again.");
      setSaving(false);
      return;
    }
    const currentAssets = current?.assets ?? {};
    const currentCost = current?.cost_basis ?? {};
    const riskProfile: RiskProfile = current?.risk_profile ?? "balanced";

    try {
      let finalAssets: Record<string, number>;
      let finalCost: Record<string, number>;
      if (mergeMode === "replace") {
        finalAssets = assets!;
        finalCost = cost_basis ?? {};
      } else {
        finalAssets = { ...currentAssets, ...assets };
        // For each re-imported symbol, the import's buy price is authoritative:
        // use it when supplied, else CLEAR any stale prior cost so the new
        // quantity isn't paired with an old per-unit price (corrupts P/L).
        finalCost = { ...currentCost };
        for (const sym of Object.keys(assets!)) {
          if (cost_basis && sym in cost_basis) finalCost[sym] = cost_basis[sym];
          else delete finalCost[sym];
        }
      }
      await upsertPortfolio({
        user_id: userId,
        assets: finalAssets,
        cost_basis: finalCost,
        risk_profile: riskProfile,
      });
      window.location.assign("/portfolio");
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Couldn't save.");
      setSaving(false);
    }
  }

  // Live per-row hints (recomputed as the user edits — never stale).
  const seenAbove = new Set<string>();
  const rowMeta = rows.map((r) => {
    const sym = r.symbol.trim().toUpperCase();
    const duplicate = sym !== "" && seenAbove.has(sym);
    if (sym) seenAbove.add(sym);
    const qty = Number(r.quantity.trim().replace(",", "."));
    const needsQty = sym !== "" && (!r.quantity.trim() || !Number.isFinite(qty) || qty <= 0);
    return { duplicate, needsQty };
  });

  const readyCount = rows.filter((r, i) => {
    const sym = r.symbol.trim().toUpperCase();
    return (
      sym !== "" &&
      !rowMeta[i].duplicate &&
      !rowMeta[i].needsQty &&
      validations[sym]?.state !== "invalid"
    );
  }).length;
  const needFixCount = rows.length - readyCount;
  // A duplicate symbol hard-fails the save (rowsToPayload rejects it), so it must
  // also gate the Save button — otherwise the click dead-ends with a terse error.
  const hasDuplicate = rowMeta.some((m) => m.duplicate);

  return (
    <main className="min-h-screen bg-backdrop text-ink">
      <div className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
        <Link
          href="/portfolio"
          className="text-sm text-label transition-colors hover:text-ink"
        >
          ← Edit portfolio
        </Link>

        <h1 className="mt-3 font-serif text-3xl font-medium tracking-[-0.02em] sm:text-4xl">
          Import holdings
        </h1>
        <p className="mt-1 text-sm text-muted">
          Paste a CSV from your broker, or just describe your holdings in plain
          words. Review everything before it&apos;s saved.
        </p>

        {stage === "input" && (
          <div className="mt-8 space-y-4">
            {/* Mode tabs */}
            <div className="inline-flex rounded-[4px] border border-line p-1">
              {(["csv", "text"] as ImportMode[]).map((m) => (
                <button
                  key={m}
                  onClick={() => {
                    setMode(m);
                    setParseError(null);
                  }}
                  className={`min-h-[40px] rounded-[2px] px-4 py-1.5 text-sm transition-colors ${
                    mode === m ? "bg-forest text-paper" : "text-muted hover:text-ink"
                  }`}
                >
                  {m === "csv" ? "CSV / spreadsheet" : "Describe in words"}
                </button>
              ))}
            </div>

            <section className="rounded-[4px] border border-line bg-card p-5">
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder={mode === "csv" ? CSV_PLACEHOLDER : TEXT_PLACEHOLDER}
                rows={8}
                className="min-h-[180px] w-full resize-y rounded-[3px] border border-field bg-card px-3 py-2 font-mono text-sm text-ink placeholder:text-faint focus:border-forest focus:outline-none"
              />
              {mode === "csv" ? (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <label className="cursor-pointer text-sm text-forest transition-colors hover:text-forest-deep">
                    Upload a .csv file
                    <input
                      type="file"
                      accept=".csv,text/csv"
                      className="hidden"
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        if (file) setContent(await file.text());
                        e.target.value = ""; // allow re-selecting the same file
                      }}
                    />
                  </label>
                  <span className="text-xs text-faint">
                    Columns: symbol, quantity, and optional cost. Headers are
                    auto-detected.
                  </span>
                </div>
              ) : (
                <p className="mt-3 text-xs text-faint">
                  e.g. “10 shares of Apple, half a Bitcoin, 1000 Teva at ₪12”.
                  We&apos;ll resolve names to tickers — you confirm each one.
                </p>
              )}
            </section>

            <div className="flex items-center gap-4">
              <button
                onClick={handlePreview}
                disabled={parsing || !content.trim()}
                className="min-h-[40px] rounded-[2px] bg-forest px-4 py-2 font-medium text-paper transition-colors hover:bg-forest-deep disabled:opacity-50"
              >
                {parsing ? "Parsing…" : "Preview import"}
              </button>
              {parseError && (
                <span className="text-sm text-terracotta">{parseError}</span>
              )}
            </div>
          </div>
        )}

        {stage === "preview" && (
          <div className="mt-8 space-y-6">
            {/* Summary */}
            <div className="rounded-[4px] border border-line bg-inset p-4 text-sm">
              <span className="text-ink">
                {readyCount} ready
                {needFixCount > 0 && (
                  <span className="text-ochre"> · {needFixCount} need a fix</span>
                )}
              </span>
              {preview?.warnings.map((w, i) => (
                <p key={i} className="mt-1 text-xs text-ochre">
                  {w}
                </p>
              ))}
              {preview && preview.errors.length > 0 && (
                <div className="mt-2">
                  <button
                    onClick={() => setShowErrors((s) => !s)}
                    className="text-xs text-label underline transition-colors hover:text-ink"
                  >
                    {preview.errors.length} row(s) we couldn’t read{" "}
                    {showErrors ? "▲" : "▼"}
                  </button>
                  {showErrors && (
                    <ul className="mt-1 space-y-0.5">
                      {preview.errors.map((er, i) => (
                        <li key={i} className="text-xs text-faint">
                          {er.line != null ? `Line ${er.line}: ` : ""}
                          {er.reason}
                          {er.raw ? ` — ${er.raw}` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            {/* Editable rows */}
            <section>
              <div className="space-y-3">
                {rows.map((row, i) => {
                  const sym = row.symbol.trim().toUpperCase();
                  const status = sym ? validations[sym] : undefined;
                  const invalid = status?.state === "invalid";
                  const meta = rowMeta[i];
                  // Show the friendly "enter a ticker" hint when an invalid row
                  // came from a typed name — either the LLM copied the word
                  // verbatim (text mode) or it resolved a name to a still-invalid
                  // shorter ticker (input differs from the symbol).
                  const unresolved =
                    invalid &&
                    !!row.inputSymbol &&
                    (mode === "text" || row.inputSymbol.toUpperCase() !== sym);
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
                          aria-label={`Remove ${row.symbol || "holding"}`}
                          className="min-h-[40px] shrink-0 rounded-[2px] px-2 py-2 text-faint transition-colors hover:text-terracotta"
                        >
                          ✕
                        </button>
                      </div>
                      {unresolved && (
                        <p className="mt-1 pl-1 text-xs text-terracotta">
                          “{row.inputSymbol}” — enter a ticker (e.g. AAPL).
                        </p>
                      )}
                      {!unresolved && meta.duplicate && (
                        <p className="mt-1 pl-1 text-xs text-faint">
                          Already listed above — edit the first row instead.
                        </p>
                      )}
                      {!unresolved && !meta.duplicate && meta.needsQty && (
                        <p className="mt-1 pl-1 text-xs text-ochre">
                          Enter a quantity for this holding.
                        </p>
                      )}
                      {!unresolved && !meta.duplicate && !meta.needsQty && (
                        <TickerStatusLine status={status} />
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Merge vs replace */}
            <section className="space-y-2">
              <div className="inline-flex rounded-[4px] border border-line p-1">
                {(["merge", "replace"] as MergeMode[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMergeMode(m)}
                    className={`min-h-[40px] rounded-[2px] px-3 py-1.5 text-sm transition-colors ${
                      mergeMode === m ? "bg-forest text-paper" : "text-muted hover:text-ink"
                    }`}
                  >
                    {m === "merge" ? "Add to my portfolio" : "Replace everything"}
                  </button>
                ))}
              </div>
              <p className="text-xs text-faint">
                {mergeMode === "merge"
                  ? "Imported holdings are added to what you already have (matching symbols are updated)."
                  : "Your current holdings are replaced entirely by this import."}
              </p>
            </section>

            {/* Save */}
            <section className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
              <button
                onClick={handleSave}
                disabled={saving || hasInvalidTicker || hasDuplicate || rows.length === 0}
                className="min-h-[40px] rounded-[2px] bg-forest px-4 py-2 font-medium text-paper transition-colors hover:bg-forest-deep disabled:opacity-50"
              >
                {saving
                  ? "Saving…"
                  : mergeMode === "merge"
                    ? "Add to portfolio"
                    : "Replace portfolio"}
              </button>
              <button
                onClick={() => {
                  setStage("input");
                  setSaveError(null);
                }}
                className="text-sm text-label transition-colors hover:text-ink"
              >
                ← Back
              </button>
              {hasInvalidTicker && !saveError && (
                <span className="text-sm text-terracotta">
                  Fix the invalid ticker(s) before saving.
                </span>
              )}
              {hasDuplicate && !hasInvalidTicker && !saveError && (
                <span className="text-sm text-terracotta">
                  Remove or merge the duplicate holding(s) before saving.
                </span>
              )}
              {saveError && <span className="text-sm text-terracotta">{saveError}</span>}
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
