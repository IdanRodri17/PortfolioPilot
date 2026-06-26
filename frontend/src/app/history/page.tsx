"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { getReportsHistory, getReport, getReportSeries } from "@/lib/api";
import type {
  ReportSummary,
  ReportDetail,
  ReportSeriesPoint,
} from "@/lib/types";
import { FinalReportView } from "@/components/FinalReportView";

import { useUserId } from "@/lib/useUserId";
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const pct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;

interface TrendPoint {
  label: string;
  totalUsd: number;
  portfolioPct: number;
  sp500Pct: number | null;
  nasdaqPct: number | null;
}

interface TrendTooltipProps {
  active?: boolean;
  payload?: { payload: TrendPoint }[];
}

const SP500_COLOR = "#A89E8E"; // warm gray
const NASDAQ_COLOR = "#B07D2B"; // ochre

function TrendTooltip({ active, payload }: TrendTooltipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-[3px] border border-line bg-card px-3 py-2 text-xs shadow-lg">
      <p className="text-muted">{p.label}</p>
      <p className="font-mono text-ink">
        Portfolio {pct(p.portfolioPct)}{" "}
        <span className="text-faint">({usd.format(p.totalUsd)})</span>
      </p>
      {p.sp500Pct != null && (
        <p className="font-mono text-faint">S&amp;P 500 {pct(p.sp500Pct)}</p>
      )}
      {p.nasdaqPct != null && (
        <p className="font-mono text-ochre">Nasdaq {pct(p.nasdaqPct)}</p>
      )}
    </div>
  );
}

function ValueTrendChart({ series }: { series: ReportSeriesPoint[] }) {
  const [showSp500, setShowSp500] = useState(true);
  const [showNasdaq, setShowNasdaq] = useState(true);

  // A line needs at least two points to read as a trend.
  if (series.length < 2) return null;
  // Plot % RETURN from the first report (each series rebased to 0%) so the
  // portfolio and the indices are directly comparable — raw index values are too
  // large to show their moves next to a portfolio value (V24.2). sp500_usd /
  // nasdaq_usd are already rebased to the first total, so dividing by it gives
  // each index's own % return.
  const firstTotal = series[0].total_usd;
  const data: TrendPoint[] = series.map((p) => ({
    label: new Date(p.generated_at).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    }),
    totalUsd: p.total_usd,
    portfolioPct: firstTotal ? (p.total_usd / firstTotal - 1) * 100 : 0,
    sp500Pct:
      firstTotal && p.sp500_usd != null ? (p.sp500_usd / firstTotal - 1) * 100 : null,
    nasdaqPct:
      firstTotal && p.nasdaq_usd != null
        ? (p.nasdaq_usd / firstTotal - 1) * 100
        : null,
  }));
  const hasSp500 = data.some((d) => d.sp500Pct != null);
  const hasNasdaq = data.some((d) => d.nasdaqPct != null);

  return (
    <section className="mt-8 rounded-[4px] border border-line bg-card p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-serif text-lg font-medium tracking-wide text-ink">
          Performance vs the market
        </h2>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
          <span className="flex items-center gap-1.5 text-muted">
            <span className="h-0.5 w-4 rounded bg-forest" /> Your portfolio
          </span>
          {hasSp500 && (
            <label className="flex cursor-pointer items-center gap-1.5 text-muted">
              <input
                type="checkbox"
                checked={showSp500}
                onChange={(e) => setShowSp500(e.target.checked)}
                className="h-3 w-3 cursor-pointer accent-[#A89E8E]"
              />
              <span
                className="h-0.5 w-4 rounded"
                style={{ backgroundColor: SP500_COLOR }}
              />{" "}
              S&amp;P 500
            </label>
          )}
          {hasNasdaq && (
            <label className="flex cursor-pointer items-center gap-1.5 text-muted">
              <input
                type="checkbox"
                checked={showNasdaq}
                onChange={(e) => setShowNasdaq(e.target.checked)}
                className="h-3 w-3 cursor-pointer accent-[#B07D2B]"
              />
              <span
                className="h-0.5 w-4 rounded"
                style={{ backgroundColor: NASDAQ_COLOR }}
              />{" "}
              Nasdaq
            </label>
          )}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 5, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#ECE5D8" strokeDasharray="3 3" />
          <XAxis
            dataKey="label"
            stroke="#8A8175"
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: "#ECE5D8" }}
            minTickGap={24}
          />
          <YAxis
            stroke="#8A8175"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            width={48}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
          />
          <Tooltip content={<TrendTooltip />} />
          {/* Baseline: 0% = the first report. */}
          <ReferenceLine y={0} stroke="#D8CFC0" strokeDasharray="2 2" />
          {hasSp500 && showSp500 && (
            <Line
              type="monotone"
              dataKey="sp500Pct"
              stroke={SP500_COLOR}
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          )}
          {hasNasdaq && showNasdaq && (
            <Line
              type="monotone"
              dataKey="nasdaqPct"
              stroke={NASDAQ_COLOR}
              strokeWidth={1.5}
              strokeDasharray="2 3"
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          )}
          <Line
            type="monotone"
            dataKey="portfolioPct"
            stroke="#2F5D45"
            strokeWidth={2}
            dot={{ r: 3, fill: "#2F5D45" }}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </section>
  );
}

export default function HistoryPage() {
  const { userId } = useUserId();
  const [load, setLoad] = useState<"loading" | "ready" | "error">("loading");
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [series, setSeries] = useState<ReportSeriesPoint[]>([]);
  const [selected, setSelected] = useState<ReportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);
  // The opened report renders directly under its own row; scroll it into view so
  // a click always visibly lands somewhere.
  const detailRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!userId) return;
    let active = true;
    Promise.all([getReportsHistory(userId), getReportSeries(userId)])
      .then(([hist, ser]) => {
        if (!active) return;
        setReports(hist);
        setSeries(ser);
        setLoad("ready");
      })
      .catch(() => active && setLoad("error"));
    return () => {
      active = false;
    };
  }, [userId]);

  async function openReport(id: string) {
    setOpeningId(id);
    setDetailLoading(true);
    setDetailError(null);
    try {
      setSelected(await getReport(id));
    } catch {
      setSelected(null);
      setDetailError("Could not load this report. Please try again.");
    } finally {
      setDetailLoading(false);
    }
  }

  // Bring the opened report into view once it has rendered.
  useEffect(() => {
    if (selected && detailRef.current) {
      detailRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selected]);

  return (
    <main className="min-h-screen bg-backdrop text-ink">
      <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
        <div className="no-print">
          <Link href="/" className="text-sm text-label transition-colors hover:text-muted">
            ← Dashboard
          </Link>
          <h1 className="mt-3 font-serif text-3xl font-medium tracking-[-0.02em] sm:text-4xl">Report history</h1>
          <p className="mt-1 text-sm text-muted">Past analyses, newest first. Click one to view it.</p>
        </div>

        {load === "loading" && <p className="mt-8 text-sm text-faint">Loading history…</p>}
        {load === "error" && <p className="mt-8 text-sm text-terracotta">Could not load history.</p>}
        {load === "ready" && (
          <div className="no-print">
            <ValueTrendChart series={series} />
          </div>
        )}
        {load === "ready" && reports.length === 0 && (
          <p className="mt-8 rounded-[4px] border border-dashed border-line px-4 py-10 text-center text-sm text-faint">
            No reports yet. Generate one from the dashboard.
          </p>
        )}

        {load === "ready" && reports.length > 0 && (
          <ul className="mt-8 space-y-2 print:mt-0 print:space-y-0">
            {reports.map((r) => {
              const isSel = selected?.report_id === r.report_id;
              const isOpening = openingId === r.report_id;
              const change = r.change_24h_percent ?? 0;
              const up = change >= 0;
              return (
                <li key={r.report_id}>
                  <button
                    onClick={() => openReport(r.report_id)}
                    className={`no-print flex min-h-[40px] w-full items-center justify-between gap-4 rounded-[4px] border px-4 py-3 text-left transition-colors ${
                      isSel
                        ? "border-forest bg-wash-pos"
                        : "border-line bg-card hover:bg-inset"
                    }`}
                  >
                    <div>
                      <p className="font-mono text-sm text-ink">
                        {r.total_usd != null ? usd.format(r.total_usd) : "—"}
                        <span className={`ml-2 text-xs ${up ? "text-forest" : "text-terracotta"}`}>
                          {up ? "▲" : "▼"} {Math.abs(change).toFixed(2)}%
                        </span>
                      </p>
                      <p className="mt-0.5 text-xs text-faint">
                        {new Date(r.generated_at).toLocaleString()}
                      </p>
                    </div>
                    {r.confidence_flag && (
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          r.confidence_flag === "high"
                            ? "bg-wash-pos text-forest"
                            : "bg-ochre/10 text-ochre"
                        }`}
                      >
                        {r.confidence_flag}
                      </span>
                    )}
                  </button>

                  {/* The opened report renders directly under its own row. */}
                  {isOpening && detailLoading && (
                    <p className="no-print mt-3 text-sm text-faint">Loading report…</p>
                  )}
                  {isOpening && detailError && !detailLoading && (
                    <p className="no-print mt-3 text-sm text-terracotta">
                      {detailError}
                    </p>
                  )}
                  {isSel && selected && !detailLoading && (
                    <div ref={detailRef} className="mt-4 scroll-mt-6">
                      <div className="no-print mb-3 flex items-center justify-between">
                        <h2 className="font-serif text-lg font-medium tracking-wide text-muted">
                          Report · {new Date(selected.generated_at).toLocaleString()}
                        </h2>
                        <button
                          onClick={() => {
                            setSelected(null);
                            setOpeningId(null);
                          }}
                          className="text-xs text-label transition-colors hover:text-muted"
                        >
                          Close ✕
                        </button>
                      </div>
                      <FinalReportView
                        report={selected.report}
                        reportId={selected.report_id}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </main>
  );
}