"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getMemories, deleteMemories } from "@/lib/api";
import type { Memory } from "@/lib/types";

import { useUserId } from "@/lib/useUserId";
type LoadState = "loading" | "ready" | "error";

export default function MemoryPage() {
  const { userId } = useUserId();
  const [load, setLoad] = useState<LoadState>("loading");
  const [memories, setMemories] = useState<Memory[]>([]);
  const [wiping, setWiping] = useState(false);

  useEffect(() => {
    if (!userId) return;
    let active = true;
    getMemories(userId)
      .then((data) => active && (setMemories(data), setLoad("ready")))
      .catch(() => active && setLoad("error"));
    return () => {
      active = false;
    };
  }, [userId]);

  async function handleWipe() {
    if (!userId) return;
    setWiping(true);
    try {
      await deleteMemories(userId);
      setMemories([]);
    } finally {
      setWiping(false);
    }
  }

  return (
    <main className="min-h-screen bg-backdrop text-ink">
      <div className="mx-auto max-w-2xl px-6 py-10">
        <Link href="/" className="text-sm text-label transition-colors hover:text-ink">
          ← Dashboard
        </Link>
        <div className="mt-3 flex flex-col items-start justify-between gap-4 sm:flex-row">
          <div>
            <h1 className="font-serif text-3xl font-medium tracking-[-0.02em] sm:text-4xl">What PortfolioPilot remembers</h1>
            <p className="mt-1 text-sm text-muted">Insights learned from your past reports.</p>
          </div>
          {memories.length > 0 && (
            <button
              onClick={handleWipe}
              disabled={wiping}
              className="min-h-[40px] flex-shrink-0 rounded-[2px] border border-terracotta/40 bg-wash-neg px-3 py-2 text-sm font-medium text-terracotta transition-colors hover:bg-terracotta hover:text-paper disabled:opacity-50"
            >
              {wiping ? "Wiping…" : "Wipe memory"}
            </button>
          )}
        </div>

        {load === "loading" && <p className="mt-8 text-sm text-faint">Loading memory…</p>}
        {load === "error" && <p className="mt-8 text-sm text-terracotta">Could not load memory.</p>}
        {load === "ready" && memories.length === 0 && (
          <p className="mt-8 rounded-[4px] border border-dashed border-line px-4 py-10 text-center text-sm text-faint">
            Nothing remembered yet. Generate a couple of reports and insights will appear here.
          </p>
        )}
        {load === "ready" && memories.length > 0 && (
          <ul className="mt-8 space-y-3">
            {memories.map((m) => (
              <li key={m.key} className="rounded-[4px] border border-line bg-card p-4">
                <div className="flex items-start gap-3">
                  <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-forest" />
                  <div>
                    <p className="text-sm leading-relaxed text-ink">{m.insight}</p>
                    {m.created_at && (
                      <p className="mt-1 text-xs text-faint">
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