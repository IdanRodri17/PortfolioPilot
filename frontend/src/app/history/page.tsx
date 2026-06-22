"use client";

import { useEffect, useState } from "react";
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
}

interface TrendTooltipProps {
  active?: boolean;
  payload?: { payload: TrendPoint }[];
}

function TrendTooltip({ active, payload }: TrendTooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-md border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs shadow-lg">
      <p className="text-slate-400">{point.label}</p>
      <p className="font-mono text-slate-200">{usd.format(point.total)}</p>
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
  }));
  return (
    <section className="mt-8 rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="mb-4 text-sm font-medium tracking-wide text-slate-300">
        Portfolio value over time
      </h2>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 5, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
          <XAxis
            dataKey="label"
            stroke="#64748b"
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: "#1e293b" }}
            minTickGap={24}
          />
          <YAxis
            stroke="#64748b"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(v: number) => usdCompact.format(v)}
          />
          <Tooltip content={<TrendTooltip />} />
          <Line
            type="monotone"
            dataKey="total"
            stroke="#34d399"
            strokeWidth={2}
            dot={{ r: 3, fill: "#34d399" }}
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
    setDetailLoading(true);
    try {
      setSelected(await getReport(id));
    } catch {
      setSelected(null);
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-3xl px-6 py-10">
        <Link href="/" className="text-sm text-slate-500 transition-colors hover:text-slate-300">
          ← Dashboard
        </Link>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight">Report history</h1>
        <p className="mt-1 text-sm text-slate-500">Past analyses, newest first. Click one to view it.</p>

        {load === "loading" && <p className="mt-8 text-sm text-slate-600">Loading history…</p>}
        {load === "error" && <p className="mt-8 text-sm text-rose-400">Could not load history.</p>}
        {load === "ready" && <ValueTrendChart series={series} />}
        {load === "ready" && reports.length === 0 && (
          <p className="mt-8 rounded-xl border border-dashed border-slate-800 px-4 py-10 text-center text-sm text-slate-600">
            No reports yet. Generate one from the dashboard.
          </p>
        )}

        {load === "ready" && reports.length > 0 && (
          <ul className="mt-8 space-y-2">
            {reports.map((r) => {
              const isSel = selected?.report_id === r.report_id;
              const change = r.change_24h_percent ?? 0;
              const up = change >= 0;
              return (
                <li key={r.report_id}>
                  <button
                    onClick={() => openReport(r.report_id)}
                    className={`flex w-full items-center justify-between gap-4 rounded-lg border px-4 py-3 text-left transition-colors ${
                      isSel
                        ? "border-emerald-600/50 bg-emerald-500/5"
                        : "border-slate-800 bg-slate-900/40 hover:bg-slate-900"
                    }`}
                  >
                    <div>
                      <p className="text-sm text-slate-200">
                        {r.total_usd != null ? usd.format(r.total_usd) : "—"}
                        <span className={`ml-2 text-xs ${up ? "text-emerald-400" : "text-rose-400"}`}>
                          {up ? "▲" : "▼"} {Math.abs(change).toFixed(2)}%
                        </span>
                      </p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {new Date(r.generated_at).toLocaleString()}
                      </p>
                    </div>
                    {r.confidence_flag && (
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          r.confidence_flag === "high"
                            ? "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20"
                            : "bg-amber-500/10 text-amber-300 ring-1 ring-amber-500/20"
                        }`}
                      >
                        {r.confidence_flag}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        {detailLoading && <p className="mt-6 text-sm text-slate-600">Loading report…</p>}
        {selected && !detailLoading && (
          <div className="mt-8">
            <h2 className="mb-3 text-sm font-medium tracking-wide text-slate-400">
              Report · {new Date(selected.generated_at).toLocaleString()}
            </h2>
            <FinalReportView report={selected.report} reportId={selected.report_id} />
          </div>
        )}
      </div>
    </main>
  );
}