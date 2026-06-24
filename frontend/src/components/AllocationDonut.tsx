"use client";

/**
 * AllocationDonut — value-weighted portfolio allocation as a Recharts donut.
 *
 * Data comes from the report's deterministic `portfolio_composition` (V10a),
 * computed server-side by risk_agent — these slices are arithmetic, never
 * LLM-emitted. The donut is sized by each asset's USD value; the center shows
 * the total; the legend is the per-slice label, reading "SYMBOL pct% · $value".
 *
 * Recharts is v3.8.1 — we deliberately avoid the on-arc `label` render prop
 * (its geometry changed from v2 and clips in a fixed-height box) in favour of
 * a color-matched legend we fully control. Palette stays within the shared
 * slate/emerald language (no rainbow); amber is reserved for the in-flight feed.
 */

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import type { AssetAllocation } from "@/lib/types";
import { displayMoney, type BaseCurrency } from "@/lib/money";

// Largest holdings get the brighter emeralds; the tail fades into slate so the
// chart reads as "your concentration" rather than a categorical rainbow.
const PALETTE = [
  "#10b981",
  "#34d399",
  "#6ee7b7",
  "#a7f3d0",
  "#5eead4",
  "#64748b",
  "#94a3b8",
  "#cbd5e1",
];

interface DonutTooltipProps {
  active?: boolean;
  payload?: readonly { payload?: AssetAllocation }[];
}

export function AllocationDonut({
  composition,
  base,
  ilsPerUsd,
}: {
  composition: AssetAllocation[];
  base: BaseCurrency;
  ilsPerUsd: number | null;
}) {
  // Inline so it closes over the chosen base + FX rate (V17).
  function renderTooltip(props: DonutTooltipProps) {
    const slice = props.active ? props.payload?.[0]?.payload : undefined;
    if (!slice) return null;
    return (
      <div className="rounded-md border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs shadow-lg">
        <span className="font-mono text-slate-200">{slice.asset}</span>{" "}
        <span className="text-slate-400">
          {displayMoney(slice.value_usd, base, ilsPerUsd)} · {slice.pct}%
        </span>
      </div>
    );
  }

  if (composition.length === 0) {
    return (
      <p className="rounded-lg bg-slate-800/40 px-3 py-2 text-sm text-slate-400 ring-1 ring-slate-700/50">
        No priced holdings to chart yet.
      </p>
    );
  }

  // Center total equals the sum of the slices, so the parts always reconcile
  // to the whole shown in the hole.
  const total = composition.reduce((sum, slice) => sum + slice.value_usd, 0);

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <div className="relative h-[200px] w-[200px] shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={composition}
              dataKey="value_usd"
              nameKey="asset"
              cx="50%"
              cy="50%"
              innerRadius={62}
              outerRadius={92}
              paddingAngle={composition.length > 1 ? 2 : 0}
              stroke="none"
              isAnimationActive={false}
            >
              {composition.map((slice, i) => (
                <Cell key={slice.asset} fill={PALETTE[i % PALETTE.length]} />
              ))}
            </Pie>
            <Tooltip content={renderTooltip} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            Total
          </span>
          <span className="text-base font-semibold text-slate-100">
            {displayMoney(total, base, ilsPerUsd, { compact: true })}
          </span>
        </div>
      </div>

      <ul className="grid w-full grid-cols-1 gap-1.5 sm:grid-cols-2">
        {composition.map((slice, i) => (
          <li key={slice.asset} className="flex items-center gap-2 text-sm">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
            />
            <span className="font-mono text-slate-200">{slice.asset}</span>
            <span className="text-slate-400">{slice.pct}%</span>
            <span className="ml-auto font-mono text-xs text-slate-500">
              {displayMoney(slice.value_usd, base, ilsPerUsd)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
