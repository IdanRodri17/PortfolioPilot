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
  conservative: "border border-pos-line text-forest",
  balanced: "border border-pos-line text-forest",
  aggressive: "border border-ochre/40 text-ochre",
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
    <section className="rounded-[4px] border border-line bg-card p-5">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-faint">
        Holdings
      </h2>

      {state.status === "loading" && (
        <p className="py-6 text-center text-sm text-faint">
          Loading portfolio…
        </p>
      )}

      {state.status === "error" && (
        <p className="py-6 text-center text-sm text-terracotta">
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
            <span className="text-xs text-faint">
              {Object.keys(state.data.assets).length} assets
            </span>
          </div>

          <ul className="space-y-1">
            {Object.entries(state.data.assets)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([symbol, qty]) => (
                <li
                  key={symbol}
                  className="flex items-center justify-between rounded-[2px] px-3 py-2 odd:bg-chip"
                >
                  <span className="rounded-[2px] bg-chip px-1.5 py-0.5 font-mono text-xs text-ink">
                    {symbol}
                  </span>
                  <span className="font-mono text-sm text-label">{qty}</span>
                </li>
              ))}
          </ul>
        </>
      )}
    </section>
  );
}
