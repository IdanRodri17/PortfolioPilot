"use client";

/**
 * V4b step 1 smoke test — browser -> backend health check.
 *
 * This is a Client Component ("use client") on purpose. CORS only applies
 * to requests the browser makes; a Server Component fetch would run on the
 * Next.js Node server (server-to-server, same as curl) and bypass CORS
 * entirely — it would pass even if the middleware were broken, proving
 * nothing. Running the fetch client-side in useEffect is what exercises
 * the :3000 -> :8000 origin boundary the CORS middleware exists to permit.
 *
 * This page is temporary scaffolding. Step 4 replaces it with the real
 * dashboard. It exists only to turn step 1's commit green and to be the
 * first browser (not curl) to reach the API.
 */

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

type HealthState =
  | { status: "loading" }
  | { status: "ok"; body: unknown }
  | { status: "error"; message: string };

export default function Home() {
  const [health, setHealth] = useState<HealthState>({ status: "loading" });

  useEffect(() => {
    // Fires once on mount, in the browser. If CORS is misconfigured the
    // browser rejects the response before our code sees it, surfacing as
    // a TypeError ("Failed to fetch") in the catch — the classic CORS
    // block symptom. A clean {"status":"ok"} body means CORS works.
    fetch(`${API_BASE}/api/health`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((body) => setHealth({ status: "ok", body }))
      .catch((err) => setHealth({ status: "error", message: String(err) }));
  }, []);

  return (
    <main className="p-8 font-sans">
      <h1 className="text-xl font-semibold">PortfolioPilot — frontend skeleton</h1>
      <p className="mt-2 text-sm text-gray-600">
        Backend health check (browser → :8000, through CORS):
      </p>
      <pre className="mt-3 rounded bg-gray-100 p-3 text-sm">
        {JSON.stringify(health, null, 2)}
      </pre>
    </main>
  );
}