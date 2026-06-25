"use client";

/**
 * /settings — Delivery preference configuration (V7d).
 *
 * Loads the current preference via GET /api/delivery-preferences/idan_demo,
 * lets the user configure channels + cadence + timing, and persists via PUT.
 * The Telegram connect button calls POST /api/telegram/connect and updates
 * telegram_connected in local state without a full reload.
 *
 * Design: the Editorial light theme — warm paper surfaces, forest-green for
 * active/success, terracotta for errors, ochre for warnings; hairline borders,
 * via the shared @theme tokens (bg-card, border-line, text-ink, …).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getDeliveryPreferences,
  putDeliveryPreferences,
  connectTelegram,
  previewAlerts,
  previewDigest,
  authHeaders,
} from "@/lib/api";
import type {
  DeliveryPreference,
  DeliveryPreferencesView,
  DeliveryPreferenceInput,
  AlertPreview,
  DigestPreview,
  Cadence,
} from "@/lib/types";

import { useUserId } from "@/lib/useUserId";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

const TIMEZONES = [
  "Asia/Jerusalem",
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Tokyo",
  "Australia/Sydney",
];

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// ─── helpers ───────────────────────────────────────────────────────────────

function defaultForm(): DeliveryPreferenceInput {
  return {
    deliver_telegram: false,
    deliver_email: false,
    cadence: "daily",
    interval_days: null,
    weekday: null,
    send_time_local: "08:00",
    timezone: "Asia/Jerusalem",
    enabled: true,
    digest_mode: "full",
    alerts_enabled: false,
    alert_price_move_pct: null,
    alert_portfolio_move_pct: null,
    alert_concentration_pct: null,
    alert_cooldown_hours: 12,
  };
}

function preferenceToForm(p: DeliveryPreference): DeliveryPreferenceInput {
  return {
    deliver_telegram: p.deliver_telegram,
    deliver_email: p.deliver_email,
    cadence: p.cadence,
    interval_days: p.interval_days,
    weekday: p.weekday,
    // backend stores "HH:MM:SS"; <input type="time"> wants "HH:MM"
    send_time_local: p.send_time_local.slice(0, 5),
    timezone: p.timezone,
    enabled: p.enabled,
    digest_mode: p.digest_mode,
    alerts_enabled: p.alerts_enabled,
    alert_price_move_pct: p.alert_price_move_pct,
    alert_portfolio_move_pct: p.alert_portfolio_move_pct,
    alert_concentration_pct: p.alert_concentration_pct,
    alert_cooldown_hours: p.alert_cooldown_hours,
  };
}

// Default thresholds applied when a rule's checkbox is first ticked.
const ALERT_DEFAULTS = {
  alert_price_move_pct: 5,
  alert_portfolio_move_pct: 5,
  alert_concentration_pct: 40,
} as const;

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// ─── component ─────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { userId } = useUserId();
  const [view, setView] = useState<DeliveryPreferencesView | null>(null);
  const [form, setForm] = useState<DeliveryPreferenceInput>(defaultForm());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [runningNow, setRunningNow] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<AlertPreview | null>(null);
  const [previewingDigest, setPreviewingDigest] = useState(false);
  const [digestPreview, setDigestPreview] = useState<DigestPreview | null>(null);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [runNowMsg, setRunNowMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) return; // wait for the session to resolve
    getDeliveryPreferences(userId)
      .then((v) => {
        setView(v);
        if (v.preference) setForm(preferenceToForm(v.preference));
      })
      .catch((e) => console.error("Failed to load delivery preferences:", e))
      .finally(() => setLoading(false));
  }, [userId]);

  function patch<K extends keyof DeliveryPreferenceInput>(
    key: K,
    value: DeliveryPreferenceInput[K],
  ) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  // Tick/untick an alert rule: ticking restores its default threshold, unticking
  // sets it to null (off). The number input edits the value while ticked.
  function toggleRule(
    key: keyof typeof ALERT_DEFAULTS,
    on: boolean,
  ) {
    patch(key, on ? ALERT_DEFAULTS[key] : null);
    setPreview(null);
  }

  async function handlePreview() {
    setPreviewing(true);
    setPreview(null);
    try {
      setPreview(await previewAlerts(userId!));
    } catch (e) {
      setPreview({ alerts: [], skipped: errMsg(e) });
    } finally {
      setPreviewing(false);
    }
  }

  async function handlePreviewDigest() {
    setPreviewingDigest(true);
    setDigestPreview(null);
    try {
      setDigestPreview(await previewDigest(userId!));
    } catch (e) {
      setDigestPreview({ available: false, reason: errMsg(e) });
    } finally {
      setPreviewingDigest(false);
    }
  }

  function handleCadenceChange(newCadence: Cadence) {
    setForm((f) => ({
      ...f,
      cadence: newCadence,
      interval_days: newCadence === "every_n_days" ? (f.interval_days ?? 2) : null,
      weekday: newCadence === "weekly" ? (f.weekday ?? 0) : null,
    }));
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg(null);
    try {
      const saved = await putDeliveryPreferences(userId!, form);
      setView((v) => (v ? { ...v, preference: saved } : v));
      setSaveMsg({ ok: true, text: "Settings saved" });
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (e) {
      setSaveMsg({ ok: false, text: errMsg(e) });
    } finally {
      setSaving(false);
    }
  }

  async function handleConnect() {
    setConnecting(true);
    setConnectError(null);
    try {
      await connectTelegram(userId!);
      setView((v) => (v ? { ...v, telegram_connected: true } : v));
    } catch (e) {
      setConnectError(errMsg(e));
    } finally {
      setConnecting(false);
    }
  }

  async function handleRunNow() {
    setRunningNow(true);
    setRunNowMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/deliveries/run-now/${userId}`, {
        method: "POST",
        headers: await authHeaders(),
      });
      const data = await res.json();
      const channels = (data.channels ?? {}) as Record<string, string>;
      const parts = Object.entries(channels).map(([ch, s]) => `${ch}: ${s}`);
      setRunNowMsg(parts.length ? parts.join(" · ") : "No channels enabled");
    } catch (e) {
      setRunNowMsg("Error: " + errMsg(e));
    } finally {
      setRunningNow(false);
      setTimeout(() => setRunNowMsg(null), 6000);
    }
  }

  // ─── loading ─────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <main className="min-h-screen bg-backdrop flex items-center justify-center">
        <p className="text-faint text-sm animate-pulse">Loading settings…</p>
      </main>
    );
  }

  // ─── render ──────────────────────────────────────────────────────────────

  return (
    <main className="min-h-screen bg-backdrop text-ink">
      <div className="mx-auto max-w-2xl px-4 sm:px-6 py-10 sm:py-12">

        {/* Header */}
        <div className="mb-8">
          <Link
            href="/"
            className="text-xs text-label hover:text-ink transition-colors"
          >
            ← Dashboard
          </Link>
          <h1 className="mt-3 font-serif font-medium tracking-[-0.02em] text-3xl sm:text-4xl">
            Delivery settings
          </h1>
          <p className="mt-1 text-sm text-muted">
            Configure how and when PortfolioPilot sends your daily report.
          </p>
        </div>

        <div className="space-y-4">

          {/* ── 1. Enabled toggle ─────────────────────────────────────── */}
          <section className="rounded-[4px] border border-line bg-card p-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">
                  {form.enabled ? "Schedule active" : "Schedule paused"}
                </p>
                <p className="mt-0.5 text-xs text-muted">
                  {form.enabled
                    ? "Reports will be sent automatically on your schedule."
                    : "Automatic delivery is paused. You can still send manually."}
                </p>
              </div>
              <button
                onClick={() => patch("enabled", !form.enabled)}
                className={[
                  "relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent",
                  "transition-colors duration-200 focus:outline-none",
                  form.enabled ? "bg-forest" : "bg-inset",
                ].join(" ")}
                role="switch"
                aria-checked={form.enabled}
              >
                <span
                  className={[
                    "pointer-events-none inline-block h-5 w-5 rounded-full bg-paper shadow",
                    "transition duration-200",
                    form.enabled ? "translate-x-5" : "translate-x-0",
                  ].join(" ")}
                />
              </button>
            </div>
          </section>

          {/* ── 2. Channels ───────────────────────────────────────────── */}
          <section className="rounded-[4px] border border-line bg-card p-5">
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-[0.12em] text-faint">
              Channels
            </h2>
            <div className="space-y-5">

              {/* Email */}
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  id="deliver_email"
                  checked={form.deliver_email}
                  disabled={!view?.email_set}
                  onChange={(e) => patch("deliver_email", e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded accent-[#2f5d45]
                    disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                />
                <div>
                  <label
                    htmlFor="deliver_email"
                    className={`text-sm leading-none ${view?.email_set ? "text-ink" : "text-faint cursor-not-allowed"}`}
                  >
                    Email
                  </label>
                  {!view?.email_set && (
                    <p className="mt-1 text-xs text-ochre">
                      No email address on file — add one to your user profile first.
                    </p>
                  )}
                </div>
              </div>

              {/* Telegram */}
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  id="deliver_telegram"
                  checked={form.deliver_telegram}
                  disabled={!view?.telegram_connected}
                  onChange={(e) => patch("deliver_telegram", e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded accent-[#2f5d45]
                    disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                />
                <div className="flex-1">
                  <label
                    htmlFor="deliver_telegram"
                    className={`text-sm leading-none ${view?.telegram_connected ? "text-ink" : "text-faint cursor-not-allowed"}`}
                  >
                    Telegram
                  </label>
                  {view?.telegram_connected ? (
                    <p className="mt-1 text-xs text-forest">Bot connected ✓</p>
                  ) : (
                    <div className="mt-2 space-y-2">
                      <p className="text-xs text-muted">
                        Send any message to your bot first, then click Connect.
                      </p>
                      <button
                        onClick={handleConnect}
                        disabled={connecting}
                        className="text-xs px-3 py-1.5 rounded-[2px] bg-inset
                          border border-field text-ink
                          hover:border-forest hover:text-forest
                          transition-colors disabled:opacity-50"
                      >
                        {connecting ? "Connecting…" : "Connect Telegram"}
                      </button>
                      {connectError && (
                        <p className="text-xs text-terracotta">{connectError}</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* ── 3. Timing (only when schedule is active) ──────────────── */}
          {form.enabled && (
            <section className="rounded-[4px] border border-line bg-card p-5">
              <h2 className="mb-4 text-xs font-semibold uppercase tracking-[0.12em] text-faint">
                Timing
              </h2>
              <div className="space-y-4">

                {/* Cadence */}
                <div>
                  <label className="block text-xs text-label mb-1.5">
                    Cadence
                  </label>
                  <select
                    value={form.cadence}
                    onChange={(e) => handleCadenceChange(e.target.value as Cadence)}
                    className="w-full rounded-[3px] bg-card border border-field
                      px-3 py-2 text-sm text-ink
                      focus:outline-none focus:border-forest transition-colors"
                  >
                    <option value="daily">Daily</option>
                    <option value="every_n_days">Every N days</option>
                    <option value="weekly">Weekly</option>
                  </select>
                </div>

                {/* Every N days → interval_days */}
                {form.cadence === "every_n_days" && (
                  <div>
                    <label className="block text-xs text-label mb-1.5">
                      Send every how many days?
                    </label>
                    <input
                      type="number"
                      min={2}
                      value={form.interval_days ?? 2}
                      onChange={(e) =>
                        patch("interval_days", Math.max(2, parseInt(e.target.value) || 2))
                      }
                      className="w-24 rounded-[3px] bg-card border border-field
                        px-3 py-2 text-sm text-ink
                        focus:outline-none focus:border-forest transition-colors"
                    />
                  </div>
                )}

                {/* Weekly → weekday */}
                {form.cadence === "weekly" && (
                  <div>
                    <label className="block text-xs text-label mb-1.5">
                      Day of week
                    </label>
                    <select
                      value={form.weekday ?? 0}
                      onChange={(e) => patch("weekday", parseInt(e.target.value))}
                      className="w-full rounded-[3px] bg-card border border-field
                        px-3 py-2 text-sm text-ink
                        focus:outline-none focus:border-forest transition-colors"
                    >
                      {WEEKDAYS.map((d, i) => (
                        <option key={d} value={i}>
                          {d}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {/* Send time */}
                <div>
                  <label className="block text-xs text-label mb-1.5">
                    Send time (local)
                  </label>
                  <input
                    type="time"
                    value={form.send_time_local}
                    onChange={(e) => patch("send_time_local", e.target.value)}
                    className="rounded-[3px] bg-card border border-field
                      px-3 py-2 text-sm text-ink
                      focus:outline-none focus:border-forest transition-colors"
                  />
                </div>

                {/* Timezone */}
                <div>
                  <label className="block text-xs text-label mb-1.5">
                    Timezone
                  </label>
                  <select
                    value={form.timezone}
                    onChange={(e) => patch("timezone", e.target.value)}
                    className="w-full rounded-[3px] bg-card border border-field
                      px-3 py-2 text-sm text-ink
                      focus:outline-none focus:border-forest transition-colors"
                  >
                    {TIMEZONES.map((tz) => (
                      <option key={tz} value={tz}>
                        {tz}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </section>
          )}

          {/* ── 3b. Delivery content (V23) ────────────────────────────── */}
          {form.enabled && (
            <section className="rounded-xl border border-line bg-card p-5">
              <h2 className="mb-1 text-xs font-medium uppercase tracking-widest text-faint">
                What to send
              </h2>
              <p className="mb-4 text-xs text-faint">
                Choose what each scheduled message contains.
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {(
                  [
                    {
                      v: "full",
                      t: "Full report",
                      d: "The complete AI analysis every time.",
                    },
                    {
                      v: "changes_only",
                      t: "What's changed",
                      d: "A lightweight digest of what moved since your last report.",
                    },
                  ] as const
                ).map((opt) => (
                  <button
                    key={opt.v}
                    onClick={() => {
                      patch("digest_mode", opt.v);
                      setDigestPreview(null);
                    }}
                    className={`rounded-[4px] border p-3 text-left transition-colors ${
                      form.digest_mode === opt.v
                        ? "border-forest bg-wash-pos"
                        : "border-line bg-paper hover:bg-inset"
                    }`}
                  >
                    <p className="text-sm font-medium text-ink">{opt.t}</p>
                    <p className="mt-0.5 text-xs text-muted">{opt.d}</p>
                  </button>
                ))}
              </div>

              {form.digest_mode === "changes_only" && (
                <div className="mt-4 border-t border-line pt-4">
                  <button
                    onClick={handlePreviewDigest}
                    disabled={previewingDigest}
                    className="rounded-[2px] border border-line px-3 py-1.5 text-xs text-muted transition-colors hover:border-forest hover:text-forest disabled:opacity-50"
                  >
                    {previewingDigest ? "Checking…" : "Preview what's changed"}
                  </button>
                  {digestPreview && (
                    <div className="mt-3 text-sm">
                      {!digestPreview.available || !digestPreview.digest ? (
                        <p className="text-faint">
                          {digestPreview.reason ?? "Nothing to preview yet."}
                        </p>
                      ) : (
                        <div className="space-y-1.5 rounded-[4px] bg-inset p-3">
                          {digestPreview.digest.value_delta_pct != null && (
                            <p
                              className={
                                (digestPreview.digest.value_delta_usd ?? 0) >= 0
                                  ? "text-forest"
                                  : "text-terracotta"
                              }
                            >
                              {(digestPreview.digest.value_delta_usd ?? 0) >= 0
                                ? "▲"
                                : "▼"}{" "}
                              {digestPreview.digest.value_delta_pct.toFixed(2)}% since{" "}
                              {digestPreview.digest.prev_date}
                            </p>
                          )}
                          {digestPreview.digest.movers.length > 0 && (
                            <p className="font-mono text-xs text-muted">
                              Movers:{" "}
                              {digestPreview.digest.movers
                                .slice(0, 3)
                                .map(
                                  (m) =>
                                    `${m.symbol} ${m.change_24h_percent.toFixed(1)}%`,
                                )
                                .join(" · ")}
                            </p>
                          )}
                          {!digestPreview.digest.notable && (
                            <p className="text-xs italic text-faint">
                              A quiet day — nothing major moved.
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          {/* ── 4. Threshold alerts (V18) ─────────────────────────────── */}
          <section className="rounded-[4px] border border-line bg-card p-5">
            <div className="mb-4 flex items-center justify-between gap-4">
              <div>
                <h2 className="text-xs font-semibold uppercase tracking-[0.12em] text-faint">
                  Threshold alerts
                </h2>
                <p className="mt-1 text-xs text-muted">
                  Get pinged when something happens — not just on your schedule.
                  Each rule is off until you switch it on.
                </p>
              </div>
              <button
                onClick={() => patch("alerts_enabled", !form.alerts_enabled)}
                className={[
                  "relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent",
                  "transition-colors duration-200 focus:outline-none",
                  form.alerts_enabled ? "bg-forest" : "bg-inset",
                ].join(" ")}
                role="switch"
                aria-checked={form.alerts_enabled}
                aria-label="Enable threshold alerts"
              >
                <span
                  className={[
                    "pointer-events-none inline-block h-5 w-5 rounded-full bg-paper shadow",
                    "transition duration-200",
                    form.alerts_enabled ? "translate-x-5" : "translate-x-0",
                  ].join(" ")}
                />
              </button>
            </div>

            {form.alerts_enabled && !form.deliver_telegram && !form.deliver_email && (
              <p className="mb-4 rounded-[3px] bg-ochre/10 px-3 py-2 text-xs text-ochre">
                Turn on a channel above (Email or Telegram) — alerts are sent
                through the same channels as your reports.
              </p>
            )}

            <div className="space-y-3">
              {/* Price move (per holding) */}
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id="rule_price"
                  checked={form.alert_price_move_pct != null}
                  onChange={(e) => toggleRule("alert_price_move_pct", e.target.checked)}
                  className="h-4 w-4 rounded accent-[#2f5d45] cursor-pointer"
                />
                <label htmlFor="rule_price" className="flex-1 text-sm text-ink">
                  Any holding moves by
                </label>
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={form.alert_price_move_pct ?? ""}
                  disabled={form.alert_price_move_pct == null}
                  onChange={(e) => {
                    patch("alert_price_move_pct", parseFloat(e.target.value) || 0);
                    setPreview(null);
                  }}
                  className="w-20 rounded-[3px] bg-card border border-field px-2.5 py-1.5
                    text-sm text-ink text-right focus:outline-none focus:border-forest
                    disabled:opacity-40 disabled:cursor-not-allowed"
                />
                <span className="w-24 text-xs text-faint">% in 24h</span>
              </div>

              {/* Portfolio total move */}
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id="rule_portfolio"
                  checked={form.alert_portfolio_move_pct != null}
                  onChange={(e) => toggleRule("alert_portfolio_move_pct", e.target.checked)}
                  className="h-4 w-4 rounded accent-[#2f5d45] cursor-pointer"
                />
                <label htmlFor="rule_portfolio" className="flex-1 text-sm text-ink">
                  Whole portfolio moves by
                </label>
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={form.alert_portfolio_move_pct ?? ""}
                  disabled={form.alert_portfolio_move_pct == null}
                  onChange={(e) => {
                    patch("alert_portfolio_move_pct", parseFloat(e.target.value) || 0);
                    setPreview(null);
                  }}
                  className="w-20 rounded-[3px] bg-card border border-field px-2.5 py-1.5
                    text-sm text-ink text-right focus:outline-none focus:border-forest
                    disabled:opacity-40 disabled:cursor-not-allowed"
                />
                <span className="w-24 text-xs text-faint">% in 24h</span>
              </div>

              {/* Concentration */}
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id="rule_conc"
                  checked={form.alert_concentration_pct != null}
                  onChange={(e) => toggleRule("alert_concentration_pct", e.target.checked)}
                  className="h-4 w-4 rounded accent-[#2f5d45] cursor-pointer"
                />
                <label htmlFor="rule_conc" className="flex-1 text-sm text-ink">
                  Any holding exceeds
                </label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={form.alert_concentration_pct ?? ""}
                  disabled={form.alert_concentration_pct == null}
                  onChange={(e) => {
                    patch(
                      "alert_concentration_pct",
                      Math.min(100, parseFloat(e.target.value) || 0),
                    );
                    setPreview(null);
                  }}
                  className="w-20 rounded-[3px] bg-card border border-field px-2.5 py-1.5
                    text-sm text-ink text-right focus:outline-none focus:border-forest
                    disabled:opacity-40 disabled:cursor-not-allowed"
                />
                <span className="w-24 text-xs text-faint">% of portfolio</span>
              </div>

              {/* Cooldown */}
              <div className="flex items-center gap-3 border-t border-line pt-3">
                <label htmlFor="cooldown" className="flex-1 text-sm text-muted">
                  Don&apos;t repeat the same alert for
                </label>
                <input
                  id="cooldown"
                  type="number"
                  min={1}
                  max={168}
                  value={form.alert_cooldown_hours}
                  onChange={(e) =>
                    patch(
                      "alert_cooldown_hours",
                      Math.min(168, Math.max(1, parseInt(e.target.value) || 1)),
                    )
                  }
                  className="w-20 rounded-[3px] bg-card border border-field px-2.5 py-1.5
                    text-sm text-ink text-right focus:outline-none focus:border-forest"
                />
                <span className="w-24 text-xs text-faint">hours</span>
              </div>
            </div>

            {/* Preview */}
            <div className="mt-4 border-t border-line pt-4">
              <div className="flex items-center gap-3">
                <button
                  onClick={handlePreview}
                  disabled={previewing}
                  className="text-xs px-3 py-1.5 rounded-[2px] bg-inset border border-field
                    text-ink hover:border-forest hover:text-forest
                    transition-colors disabled:opacity-50"
                >
                  {previewing ? "Checking…" : "Preview alerts now"}
                </button>
                <span className="text-xs text-muted">
                  Dry-run against live prices — uses your <em>saved</em> rules, never sends.
                </span>
              </div>

              {preview && (
                <div className="mt-3 text-sm">
                  {preview.skipped ? (
                    <p className="text-muted">
                      {preview.skipped === "no alert rules set"
                        ? "No rules are switched on — tick a rule and Save, then preview."
                        : preview.skipped}
                    </p>
                  ) : preview.alerts.length === 0 ? (
                    <p className="text-forest">
                      ✓ Nothing would fire right now — you&apos;re within all your thresholds.
                    </p>
                  ) : (
                    <ul className="space-y-1.5">
                      {preview.alerts.map((a, i) => (
                        <li
                          key={i}
                          className="rounded-[3px] bg-ochre/10 px-3 py-2 text-ochre"
                        >
                          {a}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </section>

          {/* ── 5. Action row ─────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-2 rounded-[2px] bg-forest hover:bg-forest-deep
                text-paper text-sm font-medium transition-colors disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save settings"}
            </button>

            <button
              onClick={handleRunNow}
              disabled={runningNow}
              className="px-4 py-2 rounded-[2px] bg-inset hover:bg-chip
                border border-field text-muted text-sm
                transition-colors disabled:opacity-50"
            >
              {runningNow ? "Sending…" : "Send now"}
            </button>

            {saveMsg && (
              <span
                className={`text-sm ${saveMsg.ok ? "text-forest" : "text-terracotta"}`}
              >
                {saveMsg.ok ? "✓ " : "✗ "}
                {saveMsg.text}
              </span>
            )}
          </div>

          {/* Run-now result */}
          {runNowMsg && (
            <p className="text-xs text-muted bg-card rounded-[3px]
              px-4 py-2.5 border border-line">
              {runNowMsg}
            </p>
          )}

        </div>
      </div>
    </main>
  );
}
