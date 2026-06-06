"use client";

/**
 * /portfolio — the portfolio editor page.
 *
 * In the App Router, this file's location (app/portfolio/page.tsx) defines
 * the route. It loads the current portfolio via getPortfolio, lets the user
 * edit the asset map and risk profile, and persists via upsertPortfolio
 * (the V2 POST endpoint). Backed entirely by existing endpoints — no
 * backend work.
 *
 * Editable model: an array of {id, symbol, quantity} rows rather than the
 * raw {symbol: quantity} map. Editing a symbol in a map means mutating a
 * key, and add/remove invites key collisions mid-edit; an array with stable
 * ids sidesteps both. We convert rows -> map (validating along the way) only
 * at save time, mirroring the backend's PortfolioRequest rules: every symbol
 * non-empty and unique, every quantity > 0.
 *
 * This POST is the first browser request to hit a non-GET endpoint, so it's
 * the first to trigger the CORS preflight the middleware's wildcard
 * allow_methods/allow_headers answer.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { getPortfolio, upsertPortfolio } from "@/lib/api";
import type { RiskProfile } from "@/lib/types";

import { useUserId } from "@/lib/useUserId";
const RISK_PROFILES: RiskProfile[] = ["conservative", "balanced", "aggressive"];

interface Row {
  id: string;
  symbol: string;
  quantity: string; // kept as string so partial input (empty, "1.") is valid mid-edit
}

type LoadState = "loading" | "ready" | "error";
type SaveState =
  | { status: "idle" | "saving" | "saved" }
  | { status: "error"; message: string };

function rowsToAssets(rows: Row[]): { assets?: Record<string, number>; error?: string } {

  const assets: Record<string, number> = {};
  for (const r of rows) {
    const symbol = r.symbol.trim().toUpperCase();
    if (!symbol) return { error: "Every asset needs a symbol." };
    if (symbol in assets) return { error: `Duplicate symbol: ${symbol}.` };
    const qty = Number(r.quantity);
    if (!Number.isFinite(qty) || qty <= 0) {
      return { error: `Quantity for ${symbol} must be greater than 0.` };
    }
    assets[symbol] = qty;
  }
  if (Object.keys(assets).length === 0) return { error: "Add at least one asset." };
  return { assets };
}

export default function PortfolioEditorPage() {
  const { userId } = useUserId();
  const [load, setLoad] = useState<LoadState>("loading");
  const [rows, setRows] = useState<Row[]>([]);
  const [riskProfile, setRiskProfile] = useState<RiskProfile>("balanced");
  const [save, setSave] = useState<SaveState>({ status: "idle" });

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

  // Any edit invalidates the previous save/error message.
  function touched() {
    setSave((s) => (s.status === "idle" ? s : { status: "idle" }));
  }

  function updateRow(id: string, field: "symbol" | "quantity", value: string) {
    setRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)),
    );
    touched();
  }

  function addRow() {
    setRows((prev) => [...prev, { id: crypto.randomUUID(), symbol: "", quantity: "" }]);
    touched();
  }

  function removeRow(id: string) {
    setRows((prev) => prev.filter((r) => r.id !== id));
    touched();
  }

  async function handleSave() {
    const { assets, error } = rowsToAssets(rows);
    if (error) {
      setSave({ status: "error", message: error });
      return;
    }
    setSave({ status: "saving" });
    try {
      await upsertPortfolio({
        user_id: userId!,
        assets: assets!,
        risk_profile: riskProfile,
      });
      setSave({ status: "saved" });
    } catch (e) {
      setSave({ status: "error", message: String(e) });
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-2xl px-6 py-10">
        <Link
          href="/"
          className="text-sm text-slate-500 transition-colors hover:text-slate-300"
        >
          ← Dashboard
        </Link>

        <h1 className="mt-3 text-2xl font-semibold tracking-tight">Edit portfolio</h1>
        <p className="mt-1 text-sm text-slate-500">
          Update holdings and risk profile, then save.
        </p>

        {load === "loading" && (
          <p className="mt-8 text-sm text-slate-600">Loading portfolio…</p>
        )}
        {load === "error" && (
          <p className="mt-8 text-sm text-rose-400">Could not load portfolio.</p>
        )}

        {load === "ready" && (
          <div className="mt-8 space-y-8">
            {/* Risk profile */}
            <section>
              <h2 className="mb-3 text-sm font-medium tracking-wide text-slate-300">
                Risk profile
              </h2>
              <div className="inline-flex rounded-lg border border-slate-800 p-1">
                {RISK_PROFILES.map((p) => (
                  <button
                    key={p}
                    onClick={() => {
                      setRiskProfile(p);
                      touched();
                    }}
                    className={`rounded-md px-3 py-1.5 text-sm capitalize transition-colors ${
                      riskProfile === p
                        ? "bg-emerald-600 text-white"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </section>

            {/* Assets */}
            <section>
              <h2 className="mb-3 text-sm font-medium tracking-wide text-slate-300">
                Assets
              </h2>
              <div className="space-y-2">
                {rows.map((row) => (
                  <div key={row.id} className="flex items-center gap-2">
                    <input
                      value={row.symbol}
                      onChange={(e) =>
                        updateRow(row.id, "symbol", e.target.value.toUpperCase())
                      }
                      placeholder="AAPL"
                      className="w-28 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
                    />
                    <input
                      value={row.quantity}
                      onChange={(e) => updateRow(row.id, "quantity", e.target.value)}
                      type="number"
                      min="0"
                      step="any"
                      placeholder="0"
                      className="w-32 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
                    />
                    <button
                      onClick={() => removeRow(row.id)}
                      aria-label={`Remove ${row.symbol || "asset"}`}
                      className="rounded-lg px-2 py-2 text-slate-500 transition-colors hover:text-rose-400"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
              <button
                onClick={addRow}
                className="mt-3 text-sm text-emerald-400 transition-colors hover:text-emerald-300"
              >
                + Add asset
              </button>
            </section>

            {/* Save */}
            <section className="flex items-center gap-4">
              <button
                onClick={handleSave}
                disabled={save.status === "saving"}
                className="rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
              >
                {save.status === "saving" ? "Saving…" : "Save portfolio"}
              </button>
              {save.status === "saved" && (
                <span className="text-sm text-emerald-400">Saved.</span>
              )}
              {save.status === "error" && (
                <span className="text-sm text-rose-400">{save.message}</span>
              )}
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
