"use client";

/**
 * Temporary scaffolding — now doubles as the step-2 smoke test by
 * exercising lib/api.getPortfolio (and through it lib/types) against the
 * real backend. Step 4 replaces this entirely with the dashboard.
 */

import { useEffect, useState } from "react";
import { getPortfolio } from "@/lib/api";
import type { PortfolioResponse } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

type Health =
  | { status: "loading" }
  | { status: "ok"; body: unknown }
  | { status: "error"; message: string };

type Portfolio =
  | { status: "loading" }
  | { status: "ok"; data: PortfolioResponse }
  | { status: "error"; message: string };

export default function Home() {
  const [health, setHealth] = useState<Health>({ status: "loading" });
  const [portfolio, setPortfolio] = useState<Portfolio>({ status: "loading" });

  useEffect(() => {
    fetch(`${API_BASE}/api/health`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((body) => setHealth({ status: "ok", body }))
      .catch((err) => setHealth({ status: "error", message: String(err) }));

    getPortfolio("idan_demo")
      .then((data) => setPortfolio({ status: "ok", data }))
      .catch((err) => setPortfolio({ status: "error", message: String(err) }));
  }, []);

  return (
    <main className="p-8 font-sans">
      <h1 className="text-xl font-semibold">PortfolioPilot — frontend skeleton</h1>

      <p className="mt-4 text-sm text-gray-600">Backend health:</p>
      <pre className="mt-1 rounded bg-gray-100 p-3 text-sm">
        {JSON.stringify(health, null, 2)}
      </pre>

      <p className="mt-4 text-sm text-gray-600">
        getPortfolio(&quot;idan_demo&quot;) — typed via lib/api + lib/types:
      </p>
      <pre className="mt-1 rounded bg-gray-100 p-3 text-sm">
        {JSON.stringify(portfolio, null, 2)}
      </pre>
    </main>
  );
}
