"use client";

/**
 * FinalReportView — renders a completed FinalReport as a structured,
 * readable report instead of raw JSON.
 *
 * Sections mirror the FinalReport schema (schemas/report.py):
 *   - portfolio_valuation -> hero header (total value + 24h delta)
 *   - confidence          -> a small labeled meter beside the header
 *   - market_insights     -> one card per asset, sentiment colour-coded
 *   - rebalancing_recommendations -> directional rows (or an all-clear state)
 *   - summary_narrative   -> prose paragraphs
 *
 * Colour language is shared with LiveStatusFeed: emerald = positive/good,
 * rose = negative/reduce, slate = neutral. Amber stays reserved for the
 * feed's in-flight state, so it never appears here where nothing is running.
 */

import type {
  FinalReport,
  MarketInsight,
  RebalancingRecommendation,
  Sentiment,
  RecommendationAction,
  SectorConcentration,
} from "@/lib/types";
import { AllocationDonut } from "@/components/AllocationDonut";

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

function formatPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

const SENTIMENT_STYLES: Record<Sentiment, string> = {
  Positive: "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20",
  Neutral: "bg-slate-500/10 text-slate-300 ring-1 ring-slate-500/20",
  Negative: "bg-rose-500/10 text-rose-300 ring-1 ring-rose-500/20",
};

const ACTION_META: Record<
  RecommendationAction,
  { label: string; arrow: string; text: string }
> = {
  reduce: { label: "Reduce", arrow: "↓", text: "text-rose-300" },
  increase: { label: "Increase", arrow: "↑", text: "text-emerald-300" },
  hold: { label: "Hold", arrow: "→", text: "text-slate-300" },
};

function confidenceMeta(value: number): { label: string; bar: string } {
  if (value >= 0.7) return { label: "High", bar: "bg-emerald-400" };
  if (value >= 0.5) return { label: "Moderate", bar: "bg-amber-400" };
  return { label: "Low", bar: "bg-rose-400" };
}

function InsightCard({ insight }: { insight: MarketInsight }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-xs text-slate-200">
          {insight.asset}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${SENTIMENT_STYLES[insight.sentiment]}`}
        >
          {insight.sentiment}
        </span>
      </div>
      <p className="text-sm leading-relaxed text-slate-400">{insight.summary}</p>
    </div>
  );
}

function RecommendationRow({ rec }: { rec: RebalancingRecommendation }) {
  const meta = ACTION_META[rec.action];
  return (
    <div className="flex items-start gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-3">
      <span className={`mt-0.5 font-mono text-sm font-semibold ${meta.text}`}>
        {meta.arrow}
      </span>
      <div>
        <p className="text-sm text-slate-200">
          <span className={`font-medium ${meta.text}`}>{meta.label}</span>{" "}
          <span className="font-mono text-slate-300">{rec.asset}</span>{" "}
          <span className="text-slate-500">
            ({formatPercent(rec.target_change_pct)})
          </span>
        </p>
        <p className="mt-1 text-sm leading-relaxed text-slate-400">
          {rec.rationale}
        </p>
      </div>
    </div>
  );
}

const CONCENTRATION_META: Record<
  SectorConcentration["concentration"],
  { label: string; chip: string }
> = {
  high: {
    label: "High",
    chip: "bg-rose-500/10 text-rose-300 ring-1 ring-rose-500/20",
  },
  moderate: {
    label: "Moderate",
    chip: "bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/20",
  },
  low: {
    label: "Low",
    chip: "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20",
  },
  unknown: {
    label: "Unknown",
    chip: "bg-slate-500/10 text-slate-300 ring-1 ring-slate-500/20",
  },
};

// Same slate/emerald language as the allocation donut — no rainbow.
const SECTOR_COLORS = [
  "#10b981",
  "#34d399",
  "#6ee7b7",
  "#a7f3d0",
  "#5eead4",
  "#64748b",
  "#94a3b8",
  "#cbd5e1",
];

function ConcentrationSection({ data }: { data: SectorConcentration }) {
  const meta = CONCENTRATION_META[data.concentration] ?? CONCENTRATION_META.unknown;
  const scorePct = Math.round(data.diversification_score * 100);
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium tracking-wide text-slate-300">
          Sector concentration
        </h2>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${meta.chip}`}>
          {meta.label}
        </span>
      </div>

      {/* Stacked breakdown bar */}
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-800">
        {data.sectors.map((s, i) => (
          <div
            key={s.sector}
            className="h-full"
            style={{
              width: `${s.pct}%`,
              backgroundColor: SECTOR_COLORS[i % SECTOR_COLORS.length],
            }}
            title={`${s.sector} ${s.pct}%`}
          />
        ))}
      </div>

      {/* Legend */}
      <ul className="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {data.sectors.map((s, i) => (
          <li key={s.sector} className="flex items-center gap-2 text-sm">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: SECTOR_COLORS[i % SECTOR_COLORS.length] }}
            />
            <span className="text-slate-300">{s.sector}</span>
            <span className="ml-auto font-mono text-xs text-slate-500">{s.pct}%</span>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-sm leading-relaxed text-slate-400">{data.note}</p>
      <p className="mt-1 text-xs text-slate-500">
        Diversification score{" "}
        <span className="font-mono text-slate-400">{scorePct}/100</span> ·
        educational, not financial advice.
      </p>
    </section>
  );
}

export function FinalReportView({ report }: { report: FinalReport }) {
  const val = report.portfolio_valuation;
  const changePositive = val.change_24h_percent >= 0;
  const conf = confidenceMeta(report.confidence);
  const confPct = Math.round(report.confidence * 100);

  // Stable alphabetical order so the cards don't reshuffle between runs.
  const insights = [...report.market_insights].sort((a, b) =>
    a.asset.localeCompare(b.asset),
  );
  const narrativeParagraphs = report.summary_narrative
    .split("\n\n")
    .filter((p) => p.trim().length > 0);

  return (
    <div className="space-y-5">
      {/* Valuation header */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wider text-slate-500">
              Portfolio value
            </p>
            <p className="mt-1 text-3xl font-semibold text-slate-100">
              {usd.format(val.total_usd)}
            </p>
            <p
              className={`mt-1 text-sm font-medium ${changePositive ? "text-emerald-400" : "text-rose-400"}`}
            >
              {changePositive ? "▲" : "▼"} {formatPercent(val.change_24h_percent)}{" "}
              <span className="text-slate-500">24h</span>
            </p>
          </div>
          <div className="min-w-[10rem]">
            <p className="text-xs uppercase tracking-wider text-slate-500">
              Confidence · {conf.label}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                <div
                  className={`h-full rounded-full ${conf.bar}`}
                  style={{ width: `${confPct}%` }}
                />
              </div>
              <span className="font-mono text-xs text-slate-400">{confPct}%</span>
            </div>
          </div>
        </div>

        {/* Value-weighted allocation (V10a) */}
        <div className="mt-5 border-t border-slate-800 pt-4">
          <p className="mb-3 text-xs uppercase tracking-wider text-slate-500">
            Allocation
          </p>
          <AllocationDonut composition={report.portfolio_composition ?? []} />
        </div>
      </section>

      {/* Sector concentration (V11) */}
      {report.sector_concentration &&
        report.sector_concentration.sectors.length > 0 && (
          <ConcentrationSection data={report.sector_concentration} />
        )}

      {/* Market insights */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-slate-300">
          Market insights
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {insights.map((insight) => (
            <InsightCard key={insight.asset} insight={insight} />
          ))}
        </div>
      </section>

      {/* Recommendations */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-slate-300">
          Rebalancing recommendations
        </h2>
        {report.rebalancing_recommendations.length === 0 ? (
          <p className="rounded-lg bg-emerald-500/5 px-3 py-2 text-sm text-emerald-300/80 ring-1 ring-emerald-500/10">
            No changes needed — composition is within your risk profile.
          </p>
        ) : (
          <div className="space-y-2">
            {report.rebalancing_recommendations.map((rec, i) => (
              <RecommendationRow key={`${rec.asset}-${i}`} rec={rec} />
            ))}
          </div>
        )}
      </section>

      {/* Narrative */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-slate-300">
          Summary
        </h2>
        <div className="space-y-3">
          {narrativeParagraphs.map((p, i) => (
            <p key={i} className="text-sm leading-relaxed text-slate-400">
              {p}
            </p>
          ))}
        </div>
      </section>
    </div>
  );
}
