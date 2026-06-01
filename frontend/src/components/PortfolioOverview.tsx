"use client";

/**
 * PortfolioOverview — the dashboard's "what you hold" panel.
 *
 * Self-fetches the user's portfolio (getPortfolio) on mount and renders the
 * holdings as a list of ticker + quantity, with the risk profile and asset
 * count in the header.
 *
 * Why holdings-by-quantity and not a value-weighted allocation pie:
 *   A true allocation pie needs per-asset value (quantity x price). The
 *   frontend has quantities but not prices — the risk_agent computes the
 *   value-weighted composition server-side, but that is deliberately not
 *   routed through the synthesizer's FinalReport (deterministic numbers
 *   should not pass through the LLM). Exposing that composition is a clean
 *   V5 change; until then a quantity pie would misrepresent allocation, so
 *   we show an honest holdings list. The value-weighted Recharts pie lands
 *   in V5 once the composition is surfaced.
 */

import { useEffect, useState } from "react";
import { getPortfolio } from "@/lib/api";
import type { PortfolioResponse, RiskProfile } from "@/lib/types";

const RISK_STYLES: Record<RiskProfile, string> = {
  conservative: "bg-sky-500/10 text-sky-300 ring-1 ring-sky-500/20",
  balanced: "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20",
  aggressive: "bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/20",
};

type State =
  | { status: "loading" }
  | { status: "ok"; data: PortfolioResponse }
  | { status: "error" };

export function PortfolioOverview({ userId }: { userId: string }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    // `active` guards against a state update after unmount (and against
    // React 18 Strict Mode's double-invoke in dev firing two fetches).
    let active = true;
    getPortfolio(userId)
      .then((data) => active && setState({ status: "ok", data }))
      .catch(() => active && setState({ status: "error" }));
    return () => {
      active = false;
    };
  }, [userId]);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="mb-3 text-sm font-medium tracking-wide text-slate-300">
        Holdings
      </h2>

      {state.status === "loading" && (
        <p className="py-6 text-center text-sm text-slate-600">
          Loading portfolio…
        </p>
      )}

      {state.status === "error" && (
        <p className="py-6 text-center text-sm text-rose-400">
          Could not load portfolio.
        </p>
      )}

      {state.status === "ok" && (
        <>
          <div className="mb-4 flex items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${RISK_STYLES[state.data.risk_profile]}`}
            >
              {state.data.risk_profile}
            </span>
            <span className="text-xs text-slate-500">
              {Object.keys(state.data.assets).length} assets
            </span>
          </div>

          <ul className="space-y-1">
            {Object.entries(state.data.assets)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([symbol, qty]) => (
                <li
                  key={symbol}
                  className="flex items-center justify-between rounded-lg px-3 py-2 odd:bg-slate-900/40"
                >
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-xs text-slate-200">
                    {symbol}
                  </span>
                  <span className="font-mono text-sm text-slate-300">{qty}</span>
                </li>
              ))}
          </ul>
        </>
      )}
    </section>
  );
}
