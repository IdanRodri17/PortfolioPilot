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
 * Theme: Editorial (warm light). Colour language — forest = positive/good,
 * terracotta = negative/reduce, ochre = caution. The whole report is a
 * container-query context (`@container`), so on a wide screen the body lays out
 * two-up and on a phone every widget stacks one under another.
 */

import { useEffect, useState } from "react";
import type {
  FinalReport,
  MarketInsight,
  RebalancingRecommendation,
  Sentiment,
  RecommendationAction,
  SectorConcentration,
  ReportDiff,
  AdviceReview,
} from "@/lib/types";
import { AllocationDonut } from "@/components/AllocationDonut";
import { SinceLastReport } from "@/components/SinceLastReport";
import { AdviceReportCard } from "@/components/AdviceReportCard";
import { ReportChat } from "@/components/ReportChat";
import { displayMoney } from "@/lib/money";
import { useBaseCurrency } from "@/lib/useBaseCurrency";
import { getFxRate } from "@/lib/api";

function formatPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

const SENTIMENT_STYLES: Record<Sentiment, string> = {
  Positive: "bg-wash-pos text-forest",
  Neutral: "bg-chip text-label",
  Negative: "bg-wash-neg text-terracotta",
};

const ACTION_META: Record<
  RecommendationAction,
  { label: string; arrow: string; text: string }
> = {
  reduce: { label: "Reduce", arrow: "↓", text: "text-terracotta" },
  increase: { label: "Increase", arrow: "↑", text: "text-forest" },
  hold: { label: "Hold", arrow: "→", text: "text-label" },
};

function confidenceMeta(value: number): { label: string; bar: string } {
  if (value >= 0.7) return { label: "High", bar: "bg-forest" };
  if (value >= 0.5) return { label: "Moderate", bar: "bg-ochre" };
  return { label: "Low", bar: "bg-terracotta" };
}

// Section heading — Spectral serif, per the Editorial type scale.
function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 font-serif text-lg font-normal text-ink">{children}</h2>
  );
}

function InsightCard({ insight }: { insight: MarketInsight }) {
  return (
    <div className="rounded-[4px] border border-line bg-card p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded-[2px] bg-chip px-1.5 py-0.5 font-mono text-xs text-ink">
          {insight.asset}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${SENTIMENT_STYLES[insight.sentiment]}`}
        >
          {insight.sentiment}
        </span>
      </div>
      <p className="text-sm leading-relaxed text-muted">{insight.summary}</p>
    </div>
  );
}

function RecommendationRow({ rec }: { rec: RebalancingRecommendation }) {
  const meta = ACTION_META[rec.action];
  return (
    <div className="flex items-start gap-3 rounded-[4px] border border-line bg-card p-3">
      <span className={`mt-0.5 font-serif text-lg font-medium ${meta.text}`}>
        {meta.arrow}
      </span>
      <div>
        <p className="text-sm text-ink">
          <span className={`font-medium ${meta.text}`}>{meta.label}</span>{" "}
          <span className="font-mono text-ink-soft">{rec.asset}</span>{" "}
          <span className="text-faint">
            ({formatPercent(rec.target_change_pct)})
          </span>
        </p>
        <p className="mt-1 text-sm leading-relaxed text-muted">{rec.rationale}</p>
      </div>
    </div>
  );
}

const CONCENTRATION_META: Record<
  SectorConcentration["concentration"],
  { label: string; chip: string }
> = {
  high: { label: "High", chip: "border border-neg-line bg-wash-neg text-terracotta" },
  moderate: { label: "Moderate", chip: "bg-ochre/10 text-ochre" },
  low: { label: "Low", chip: "border border-pos-line bg-wash-pos text-forest" },
  unknown: { label: "Unknown", chip: "bg-chip text-label" },
};

// Editorial green ramp (largest slice first); neutrals tail off for long lists.
const SECTOR_COLORS = [
  "#2f5d45",
  "#4a7a5c",
  "#6e9a7e",
  "#9dbca6",
  "#c9d8cc",
  "#a89e8e",
  "#cdbfa0",
];

function ConcentrationSection({ data }: { data: SectorConcentration }) {
  const meta = CONCENTRATION_META[data.concentration] ?? CONCENTRATION_META.unknown;
  const scorePct = Math.round(data.diversification_score * 100);
  return (
    <section className="h-full rounded-[4px] border border-line bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-serif text-lg font-normal text-ink">
          Sector concentration
        </h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.chip}`}>
          {meta.label}
        </span>
      </div>

      {/* Stacked breakdown bar */}
      <div className="flex h-2.5 w-full gap-0.5 overflow-hidden rounded-full bg-line">
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
            <span className="text-ink-soft">{s.sector}</span>
            <span className="ml-auto font-mono text-xs text-faint">{s.pct}%</span>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-sm leading-relaxed text-muted">{data.note}</p>
      <p className="mt-1 text-xs text-faint">
        Diversification score{" "}
        <span className="font-mono text-muted">{scorePct}/100</span> ·
        educational, not financial advice.
      </p>
    </section>
  );
}

// Toolbar button (Share / Export) — hairline, no glow.
const toolBtn =
  "rounded-[2px] border border-line px-3 py-1.5 text-xs text-muted transition-colors hover:bg-inset";

export function FinalReportView({
  report,
  diff,
  adviceReview,
  reportId,
  streamingNarrative,
  narrativeStreaming,
}: {
  report: FinalReport;
  diff?: ReportDiff | null;
  adviceReview?: AdviceReview | null;
  reportId?: string | null;
  // V19: live narrative streaming. While narrativeStreaming is true the summary
  // renders from streamingNarrative (typing); otherwise it uses the report's
  // authoritative summary_narrative (history, share, or once typing finishes).
  streamingNarrative?: string;
  narrativeStreaming?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [base, setBase] = useBaseCurrency();
  const [ilsPerUsd, setIlsPerUsd] = useState<number | null>(null);

  // Fetch the USD->ILS rate once so the ₪ base can be selected (V17).
  useEffect(() => {
    let active = true;
    getFxRate()
      .then((r) => active && setIlsPerUsd(r.ils_per_usd))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  function shareLink() {
    if (!reportId) return;
    const url = `${window.location.origin}/r/${reportId}`;
    void navigator.clipboard?.writeText(url).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => {},
    );
  }

  const val = report.portfolio_valuation;
  const changePositive = val.change_24h_percent >= 0;
  const conf = confidenceMeta(report.confidence);
  const confPct = Math.round(report.confidence * 100);

  // Stable alphabetical order so the cards don't reshuffle between runs.
  const insights = [...report.market_insights].sort((a, b) =>
    a.asset.localeCompare(b.asset),
  );
  const hasConcentration =
    !!report.sector_concentration &&
    report.sector_concentration.sectors.length > 0;

  // V19: render the streamed text while it types in; otherwise the full,
  // authoritative narrative (the streamed and final text are identical once done).
  const liveNarrative = narrativeStreaming === true;
  const narrativeSource = liveNarrative
    ? streamingNarrative ?? ""
    : report.summary_narrative;
  const narrativeParagraphs = narrativeSource
    .split("\n\n")
    .filter((p) => p.trim().length > 0);

  return (
    <div className="@container space-y-5">
      {/* Share / export (V15b) — hidden in the printed PDF */}
      <div className="no-print flex flex-wrap items-center justify-end gap-2">
        <div className="inline-flex overflow-hidden rounded-[2px] border border-line text-xs">
          <button
            onClick={() => setBase("USD")}
            className={`px-2.5 py-1.5 transition-colors ${
              base === "USD"
                ? "bg-inset text-ink"
                : "text-muted hover:text-ink"
            }`}
          >
            $ USD
          </button>
          <button
            onClick={() => setBase("ILS")}
            disabled={ilsPerUsd == null}
            title={ilsPerUsd == null ? "Exchange rate unavailable" : "Show in shekels"}
            className={`px-2.5 py-1.5 transition-colors disabled:opacity-40 ${
              base === "ILS"
                ? "bg-inset text-ink"
                : "text-muted hover:text-ink"
            }`}
          >
            ₪ ILS
          </button>
        </div>
        {reportId && (
          <button onClick={shareLink} className={toolBtn}>
            {copied ? "Link copied" : "Share"}
          </button>
        )}
        <button onClick={() => window.print()} className={toolBtn}>
          Export PDF
        </button>
      </div>

      {/* Since-last-report diff strip (V12b) — only on a freshly streamed report */}
      {diff && <SinceLastReport diff={diff} />}

      {/* Valuation header */}
      <section className="rounded-[4px] border border-line bg-card p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-faint">
              Portfolio value
            </p>
            <p className="mt-1.5 font-serif text-4xl font-medium tracking-[-0.02em] text-ink sm:text-5xl">
              {displayMoney(val.total_usd, base, ilsPerUsd)}
            </p>
            <p
              className={`mt-1.5 text-sm font-semibold ${changePositive ? "text-forest" : "text-terracotta"}`}
            >
              {changePositive ? "▲" : "▼"} {formatPercent(val.change_24h_percent)}{" "}
              <span className="font-normal text-faint">past 24h</span>
            </p>
            {/* Cost-basis total return (V20) — only when buy prices are set */}
            {val.total_gain_loss_usd != null && val.total_gain_loss_pct != null && (
              <p
                className={`mt-1 text-sm font-semibold ${val.total_gain_loss_usd >= 0 ? "text-forest" : "text-terracotta"}`}
              >
                {val.total_gain_loss_usd >= 0 ? "▲" : "▼"}{" "}
                {formatPercent(val.total_gain_loss_pct)}{" "}
                <span className="font-mono font-normal">
                  ({displayMoney(val.total_gain_loss_usd, base, ilsPerUsd)})
                </span>{" "}
                <span className="font-normal text-faint">return on cost</span>
              </p>
            )}
            {/* Benchmark comparison (V24) — your 24h vs the market */}
            {val.benchmark_24h && val.benchmark_24h.length > 0 && (
              <p className="mt-1.5 text-xs text-faint">
                vs{" "}
                {val.benchmark_24h.map((b, i) => (
                  <span key={b.symbol}>
                    {i > 0 && " · "}
                    {b.name}{" "}
                    <span
                      className={`font-mono ${b.change_24h_percent >= 0 ? "text-forest" : "text-terracotta"}`}
                    >
                      {formatPercent(b.change_24h_percent)}
                    </span>
                  </span>
                ))}
              </p>
            )}
          </div>
          <div className="min-w-[10rem]">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-faint">
              Confidence · {conf.label}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                <div
                  className={`h-full rounded-full ${conf.bar}`}
                  style={{ width: `${confPct}%` }}
                />
              </div>
              <span className="font-mono text-xs text-muted">{confPct}%</span>
            </div>
          </div>
        </div>

        {/* Value-weighted allocation (V10a) */}
        <div className="mt-5 border-t border-line pt-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-faint">
            Allocation
          </p>
          <AllocationDonut
            composition={report.portfolio_composition ?? []}
            base={base}
            ilsPerUsd={ilsPerUsd}
          />
        </div>
      </section>

      {/* Market insights — full width, multi-column card wall */}
      <section className="rounded-[4px] border border-line bg-card p-5">
        <SectionHeading>Market insights</SectionHeading>
        <div className="grid gap-3 @xl:grid-cols-2 @4xl:grid-cols-3">
          {insights.map((insight) => (
            <InsightCard key={insight.asset} insight={insight} />
          ))}
        </div>
      </section>

      {/* Concentration + recommendations sit two-up (equal height) on a wide screen, stack on phone */}
      <div className="grid gap-5 @2xl:grid-cols-2 @2xl:items-stretch">
        {hasConcentration && (
          <ConcentrationSection data={report.sector_concentration!} />
        )}

        <section className="h-full rounded-[4px] border border-line bg-card p-5">
          <SectionHeading>Rebalancing recommendations</SectionHeading>
          {report.rebalancing_recommendations.length === 0 ? (
            <p className="rounded-[4px] bg-wash-pos px-3 py-2 text-sm text-forest">
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
      </div>

      {/* AI self-grading of the prior report's calls (V13) */}
      {adviceReview && <AdviceReportCard review={adviceReview} />}

      {/* Narrative — measure capped for readability even on a wide report */}
      <section className="rounded-[4px] border border-line bg-card p-5">
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-faint">
          Summary
        </p>
        <div className="space-y-3">
          {narrativeParagraphs.length === 0 && liveNarrative && (
            <p className="no-print text-sm italic leading-relaxed text-faint">
              Writing summary
              <span className="ml-0.5 animate-pulse text-forest">▋</span>
            </p>
          )}
          {narrativeParagraphs.map((p, i) =>
            i === 0 ? (
              <p
                key={i}
                className="font-serif text-[17px] leading-relaxed text-ink-soft"
              >
                {p}
                {liveNarrative && narrativeParagraphs.length === 1 && (
                  <span className="no-print ml-0.5 inline-block animate-pulse text-forest">
                    ▋
                  </span>
                )}
              </p>
            ) : (
              <p key={i} className="text-sm leading-relaxed text-muted">
                {p}
                {liveNarrative && i === narrativeParagraphs.length - 1 && (
                  <span className="no-print ml-0.5 inline-block animate-pulse text-forest">
                    ▋
                  </span>
                )}
              </p>
            ),
          )}
        </div>
      </section>

      {/* Grounded report chat (V14) — needs the report_id */}
      {reportId && <ReportChat reportId={reportId} />}
    </div>
  );
}
