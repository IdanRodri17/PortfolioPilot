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
const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

interface TrendPoint {
  label: string;
  total: number;
  benchmark: number | null;
}

interface TrendTooltipProps {
  active?: boolean;
  payload?: { payload: TrendPoint }[];
}

function TrendTooltip({ active, payload }: TrendTooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-[3px] border border-line bg-card px-3 py-2 text-xs shadow-lg">
      <p className="text-muted">{point.label}</p>
      <p className="font-mono text-ink">{usd.format(point.total)}</p>
      {point.benchmark != null && (
        <p className="font-mono text-faint">
          S&amp;P 500: {usd.format(point.benchmark)}
        </p>
      )}
    </div>
  );
}

function ValueTrendChart({ series }: { series: ReportSeriesPoint[] }) {
  // A line needs at least two points to read as a trend.
  if (series.length < 2) return null;
  const data: TrendPoint[] = series.map((p) => ({
    label: new Date(p.generated_at).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    }),
    total: p.total_usd,
    benchmark: p.benchmark_usd ?? null,
  }));
  // V24: the S&P overlay starts at the same value, so it reads as "vs the market".
  const hasBenchmark = data.some((d) => d.benchmark != null);
  return (
    <section className="mt-8 rounded-[4px] border border-line bg-card p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-serif text-lg font-medium tracking-wide text-ink">
          Portfolio value over time
        </h2>
        {hasBenchmark && (
          <div className="flex items-center gap-3 text-xs text-faint">
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 rounded bg-forest" /> Your portfolio
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 rounded bg-faint" /> S&amp;P 500
            </span>
          </div>
        )}
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
            width={56}
            tickFormatter={(v: number) => usdCompact.format(v)}
          />
          <Tooltip content={<TrendTooltip />} />
          {hasBenchmark && (
            <Line
              type="monotone"
              dataKey="benchmark"
              stroke="#A89E8E"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          )}
          <Line
            type="monotone"
            dataKey="total"
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