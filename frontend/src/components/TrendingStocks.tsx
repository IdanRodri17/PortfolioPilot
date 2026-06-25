"use client";

/**
 * TrendingStocks — a discovery card of popular US names NOT already in the
 * user's portfolio (V22). Turns the dashboard from pure analysis into a reason
 * to come back: "NVDA is down 6% today — worth a look?". Data is public + cached
 * server-side (GET /api/trending); we additionally drop anything the user holds.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { getTrending, getPortfolio } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import type { TrendingStock } from "@/lib/types";

export function TrendingStocks({ userId }: { userId?: string | null }) {
  const [stocks, setStocks] = useState<TrendingStock[] | null>(null);
  const [held, setHeld] = useState<Set<string>>(new Set());

  useEffect(() => {
    let active = true;
    getTrending(10)
      .then((s) => active && setStocks(s))
      .catch(() => active && setStocks([]));
    return () => {
      active = false;
    };
  }, []);

  // Best-effort: exclude symbols the user already holds. Failure just shows all.
  useEffect(() => {
    if (!userId) return;
    let active = true;
    getPortfolio(userId)
      .then((p) => active && setHeld(new Set(Object.keys(p.assets ?? {}))))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [userId]);

  if (stocks === null) {
    return (
      <section className="rounded-[4px] border border-line bg-card p-5">
        <p className="text-sm text-faint animate-pulse">Loading trending…</p>
      </section>
    );
  }

  const shown = stocks.filter((s) => !held.has(s.symbol)).slice(0, 8);
  if (shown.length === 0) return null;

  return (
    <section className="rounded-[4px] border border-line bg-card p-5">
      <div className="mb-3">
        <h2 className="font-serif text-lg font-normal text-ink">Trending today</h2>
        <p className="mt-0.5 text-xs text-faint">
          Popular names you don&apos;t hold — biggest movers first.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((s) => {
          const up = s.change_24h_percent >= 0;
          return (
            <div
              key={s.symbol}
              className="rounded-[4px] border border-line bg-paper p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="rounded-[2px] bg-chip px-1.5 py-0.5 font-mono text-xs text-ink">
                  {s.symbol}
                </span>
                <span
                  className={`font-mono text-xs ${up ? "text-forest" : "text-terracotta"}`}
                >
                  {up ? "▲" : "▼"} {s.change_24h_percent.toFixed(2)}%
                </span>
              </div>
              <p className="mt-2 truncate text-sm text-muted" title={s.name}>
                {s.name}
              </p>
              <div className="mt-1 flex items-center justify-between">
                <span className="font-mono text-sm text-ink">
                  {formatMoney(s.price)}
                </span>
                <Link
                  href={`/portfolio?add=${s.symbol}`}
                  className="text-xs text-forest transition-colors hover:text-forest-deep"
                >
                  + Add
                </Link>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
