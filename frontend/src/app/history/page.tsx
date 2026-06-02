"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getReportsHistory, getReport } from "@/lib/api";
import type { ReportSummary, ReportDetail } from "@/lib/types";
import { FinalReportView } from "@/components/FinalReportView";

const DEMO_USER = "idan_demo";
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export default function HistoryPage() {
  const [load, setLoad] = useState<"loading" | "ready" | "error">("loading");
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [selected, setSelected] = useState<ReportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    let active = true;
    getReportsHistory(DEMO_USER)
      .then((data) => active && (setReports(data), setLoad("ready")))
      .catch(() => active && setLoad("error"));
    return () => {
      active = false;
    };
  }, []);

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
            <FinalReportView report={selected.report} />
          </div>
        )}
      </div>
    </main>
  );
}