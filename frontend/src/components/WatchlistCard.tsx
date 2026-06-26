"use client";

/**
 * WatchlistCard — tickers the user tracks but doesn't own (V25). A reason to
 * return: "I'm watching COIN, did it move today?" Live price + 24h change per
 * symbol (GET /api/watchlist), add-by-ticker (validated via the same lookup the
 * portfolio editor uses) and remove ×. Read-only on the demo: `canEdit={false}`
 * hides the editing controls but still shows the seeded list.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { getWatchlist, putWatchlist, validateTicker } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import type { WatchlistItem } from "@/lib/types";

export function WatchlistCard({
  userId,
  canEdit = false,
}: {
  userId?: string | null;
  canEdit?: boolean;
}) {
  const [items, setItems] = useState<WatchlistItem[] | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) return;
    let active = true;
    getWatchlist(userId)
      .then((w) => active && setItems(w.items))
      .catch(() => active && setItems([]));
    return () => {
      active = false;
    };
  }, [userId]);

  // Full-replace the list, then re-read so prices reflect the new set.
  async function save(symbols: string[]) {
    if (!userId) return;
    setBusy(true);
    setError(null);
    try {
      await putWatchlist(userId, symbols);
      const w = await getWatchlist(userId);
      setItems(w.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the watchlist.");
    } finally {
      setBusy(false);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const sym = input.trim().toUpperCase();
    if (!sym || !items) return;
    if (items.some((i) => i.symbol === sym)) {
      setInput("");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const v = await validateTicker(sym);
      if (!v.found) {
        setError(`Couldn't find “${sym}”. Check the symbol.`);
        setBusy(false);
        return;
      }
      await save([...items.map((i) => i.symbol), sym]);
      setInput("");
    } catch {
      setError("Couldn't verify that symbol right now.");
      setBusy(false);
    }
  }

  async function remove(sym: string) {
    if (!items) return;
    await save(items.filter((i) => i.symbol !== sym).map((i) => i.symbol));
  }

  if (!userId) return null;

  if (items === null) {
    return (
      <section className="rounded-[4px] border border-line bg-card p-5">
        <p className="text-sm text-faint animate-pulse">Loading watchlist…</p>
      </section>
    );
  }

  // On the read-only demo with nothing seeded there's nothing to show.
  if (items.length === 0 && !canEdit) return null;

  return (
    <section className="rounded-[4px] border border-line bg-card p-5">
      <div className="mb-3">
        <h2 className="font-serif text-lg font-normal text-ink">Watching</h2>
        <p className="mt-0.5 text-xs text-faint">
          Tickers you track but don&apos;t own.
        </p>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-muted">
          Nothing yet — add a ticker below to start tracking it.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((s) => {
            const change = s.change_24h_percent;
            const up = change != null && change >= 0;
            return (
              <div
                key={s.symbol}
                className="rounded-[4px] border border-line bg-paper p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="rounded-[2px] bg-chip px-1.5 py-0.5 font-mono text-xs text-ink">
                    {s.symbol}
                  </span>
                  {change != null ? (
                    <span
                      className={`font-mono text-xs ${up ? "text-forest" : "text-terracotta"}`}
                    >
                      {up ? "▲" : "▼"} {change.toFixed(2)}%
                    </span>
                  ) : (
                    <span className="font-mono text-xs text-faint">—</span>
                  )}
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span className="font-mono text-sm text-ink">
                    {s.price != null ? formatMoney(s.price) : "—"}
                  </span>
                  {canEdit ? (
                    <button
                      type="button"
                      onClick={() => remove(s.symbol)}
                      disabled={busy}
                      aria-label={`Stop watching ${s.symbol}`}
                      className="text-xs text-faint transition-colors hover:text-terracotta disabled:opacity-50"
                    >
                      Remove ×
                    </button>
                  ) : (
                    <Link
                      href={`/portfolio?add=${s.symbol}`}
                      className="text-xs text-forest transition-colors hover:text-forest-deep"
                    >
                      + Add
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {canEdit && (
        <form onSubmit={add} className="mt-4 flex items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Add a ticker (e.g. COIN)"
            maxLength={12}
            disabled={busy}
            className="min-w-0 flex-1 rounded-[4px] border border-line bg-paper px-3 py-1.5 font-mono text-sm text-ink placeholder:text-faint focus:border-forest focus:outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-[4px] border border-forest bg-forest px-3 py-1.5 text-sm text-paper transition-colors hover:bg-forest-deep disabled:opacity-50"
          >
            {busy ? "…" : "Add"}
          </button>
        </form>
      )}

      {error && <p className="mt-2 text-xs text-terracotta">{error}</p>}
    </section>
  );
}
