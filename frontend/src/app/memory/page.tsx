"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getMemories, deleteMemories } from "@/lib/api";
import type { Memory } from "@/lib/types";

const DEMO_USER = "idan_demo";
type LoadState = "loading" | "ready" | "error";

export default function MemoryPage() {
  const [load, setLoad] = useState<LoadState>("loading");
  const [memories, setMemories] = useState<Memory[]>([]);
  const [wiping, setWiping] = useState(false);

  useEffect(() => {
    let active = true;
    getMemories(DEMO_USER)
      .then((data) => active && (setMemories(data), setLoad("ready")))
      .catch(() => active && setLoad("error"));
    return () => {
      active = false;
    };
  }, []);

  async function handleWipe() {
    setWiping(true);
    try {
      await deleteMemories(DEMO_USER);
      setMemories([]);
    } finally {
      setWiping(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-2xl px-6 py-10">
        <Link href="/" className="text-sm text-slate-500 transition-colors hover:text-slate-300">
          ← Dashboard
        </Link>
        <div className="mt-3 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">What PortfolioPilot remembers</h1>
            <p className="mt-1 text-sm text-slate-500">Insights learned from your past reports.</p>
          </div>
          {memories.length > 0 && (
            <button
              onClick={handleWipe}
              disabled={wiping}
              className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm font-medium text-rose-300 transition-colors hover:bg-rose-500/20 disabled:opacity-50"
            >
              {wiping ? "Wiping…" : "Wipe memory"}
            </button>
          )}
        </div>

        {load === "loading" && <p className="mt-8 text-sm text-slate-600">Loading memory…</p>}
        {load === "error" && <p className="mt-8 text-sm text-rose-400">Could not load memory.</p>}
        {load === "ready" && memories.length === 0 && (
          <p className="mt-8 rounded-xl border border-dashed border-slate-800 px-4 py-10 text-center text-sm text-slate-600">
            Nothing remembered yet. Generate a couple of reports and insights will appear here.
          </p>
        )}
        {load === "ready" && memories.length > 0 && (
          <ul className="mt-8 space-y-3">
            {memories.map((m) => (
              <li key={m.key} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <div className="flex items-start gap-3">
                  <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-emerald-500" />
                  <div>
                    <p className="text-sm leading-relaxed text-slate-200">{m.insight}</p>
                    {m.created_at && (
                      <p className="mt-1 text-xs text-slate-600">
                        learned {new Date(m.created_at).toLocaleDateString()}
                      </p>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}