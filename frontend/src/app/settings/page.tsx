"use client";

/**
 * /settings — Delivery preference configuration (V7d).
 *
 * Loads the current preference via GET /api/delivery-preferences/idan_demo,
 * lets the user configure channels + cadence + timing, and persists via PUT.
 * The Telegram connect button calls POST /api/telegram/connect and updates
 * telegram_connected in local state without a full reload.
 *
 * Design: matches the project's dark-fintech aesthetic (slate-950 bg,
 * emerald-500 for active/success, rose-400 for errors, amber-500 for
 * warnings, slate-900 cards with slate-800 borders).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getDeliveryPreferences,
  putDeliveryPreferences,
  connectTelegram,
} from "@/lib/api";
import type {
  DeliveryPreference,
  DeliveryPreferencesView,
  DeliveryPreferenceInput,
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
  };
}

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
      <main className="min-h-screen bg-slate-950 flex items-center justify-center">
        <p className="text-slate-500 text-sm animate-pulse">Loading settings…</p>
      </main>
    );
  }

  // ─── render ──────────────────────────────────────────────────────────────

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-2xl px-6 py-12">

        {/* Header */}
        <div className="mb-8">
          <Link
            href="/"
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            ← Dashboard
          </Link>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight">
            Delivery settings
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Configure how and when PortfolioPilot sends your daily report.
          </p>
        </div>

        <div className="space-y-4">

          {/* ── 1. Enabled toggle ─────────────────────────────────────── */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">
                  {form.enabled ? "Schedule active" : "Schedule paused"}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {form.enabled
                    ? "Reports will be sent automatically on your schedule."
                    : "Automatic delivery is paused. You can still send manually."}
                </p>
              </div>
              <button
                onClick={() => patch("enabled", !form.enabled)}
                className={[
                  "relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent",
                  "transition-colors duration-200 focus:outline-none focus-visible:ring-2",
                  "focus-visible:ring-emerald-500",
                  form.enabled ? "bg-emerald-500" : "bg-slate-700",
                ].join(" ")}
                role="switch"
                aria-checked={form.enabled}
              >
                <span
                  className={[
                    "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow",
                    "transition duration-200",
                    form.enabled ? "translate-x-5" : "translate-x-0",
                  ].join(" ")}
                />
              </button>
            </div>
          </section>

          {/* ── 2. Channels ───────────────────────────────────────────── */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <h2 className="mb-4 text-xs font-medium uppercase tracking-widest text-slate-500">
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
                  className="mt-0.5 h-4 w-4 rounded accent-emerald-500
                    disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                />
                <div>
                  <label
                    htmlFor="deliver_email"
                    className={`text-sm leading-none ${view?.email_set ? "text-slate-200" : "text-slate-500 cursor-not-allowed"}`}
                  >
                    Email
                  </label>
                  {!view?.email_set && (
                    <p className="mt-1 text-xs text-amber-500">
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
                  className="mt-0.5 h-4 w-4 rounded accent-emerald-500
                    disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                />
                <div className="flex-1">
                  <label
                    htmlFor="deliver_telegram"
                    className={`text-sm leading-none ${view?.telegram_connected ? "text-slate-200" : "text-slate-500 cursor-not-allowed"}`}
                  >
                    Telegram
                  </label>
                  {view?.telegram_connected ? (
                    <p className="mt-1 text-xs text-emerald-500">Bot connected ✓</p>
                  ) : (
                    <div className="mt-2 space-y-2">
                      <p className="text-xs text-slate-500">
                        Send any message to your bot first, then click Connect.
                      </p>
                      <button
                        onClick={handleConnect}
                        disabled={connecting}
                        className="text-xs px-3 py-1.5 rounded-lg bg-slate-800
                          border border-slate-700 text-slate-200
                          hover:border-emerald-600 hover:text-emerald-400
                          transition-colors disabled:opacity-50"
                      >
                        {connecting ? "Connecting…" : "Connect Telegram"}
                      </button>
                      {connectError && (
                        <p className="text-xs text-rose-400">{connectError}</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* ── 3. Timing (only when schedule is active) ──────────────── */}
          {form.enabled && (
            <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <h2 className="mb-4 text-xs font-medium uppercase tracking-widest text-slate-500">
                Timing
              </h2>
              <div className="space-y-4">

                {/* Cadence */}
                <div>
                  <label className="block text-xs text-slate-500 mb-1.5">
                    Cadence
                  </label>
                  <select
                    value={form.cadence}
                    onChange={(e) => handleCadenceChange(e.target.value as Cadence)}
                    className="w-full rounded-lg bg-slate-800 border border-slate-700
                      px-3 py-2 text-sm text-slate-100
                      focus:outline-none focus:border-emerald-600 transition-colors"
                  >
                    <option value="daily">Daily</option>
                    <option value="every_n_days">Every N days</option>
                    <option value="weekly">Weekly</option>
                  </select>
                </div>

                {/* Every N days → interval_days */}
                {form.cadence === "every_n_days" && (
                  <div>
                    <label className="block text-xs text-slate-500 mb-1.5">
                      Send every how many days?
                    </label>
                    <input
                      type="number"
                      min={2}
                      value={form.interval_days ?? 2}
                      onChange={(e) =>
                        patch("interval_days", Math.max(2, parseInt(e.target.value) || 2))
                      }
                      className="w-24 rounded-lg bg-slate-800 border border-slate-700
                        px-3 py-2 text-sm text-slate-100
                        focus:outline-none focus:border-emerald-600 transition-colors"
                    />
                  </div>
                )}

                {/* Weekly → weekday */}
                {form.cadence === "weekly" && (
                  <div>
                    <label className="block text-xs text-slate-500 mb-1.5">
                      Day of week
                    </label>
                    <select
                      value={form.weekday ?? 0}
                      onChange={(e) => patch("weekday", parseInt(e.target.value))}
                      className="w-full rounded-lg bg-slate-800 border border-slate-700
                        px-3 py-2 text-sm text-slate-100
                        focus:outline-none focus:border-emerald-600 transition-colors"
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
                  <label className="block text-xs text-slate-500 mb-1.5">
                    Send time (local)
                  </label>
                  <input
                    type="time"
                    value={form.send_time_local}
                    onChange={(e) => patch("send_time_local", e.target.value)}
                    className="rounded-lg bg-slate-800 border border-slate-700
                      px-3 py-2 text-sm text-slate-100
                      focus:outline-none focus:border-emerald-600 transition-colors"
                  />
                </div>

                {/* Timezone */}
                <div>
                  <label className="block text-xs text-slate-500 mb-1.5">
                    Timezone
                  </label>
                  <select
                    value={form.timezone}
                    onChange={(e) => patch("timezone", e.target.value)}
                    className="w-full rounded-lg bg-slate-800 border border-slate-700
                      px-3 py-2 text-sm text-slate-100
                      focus:outline-none focus:border-emerald-600 transition-colors"
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

          {/* ── 4. Action row ─────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500
                text-white text-sm font-medium transition-colors disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save settings"}
            </button>

            <button
              onClick={handleRunNow}
              disabled={runningNow}
              className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700
                border border-slate-700 text-slate-300 text-sm
                transition-colors disabled:opacity-50"
            >
              {runningNow ? "Sending…" : "Send now"}
            </button>

            {saveMsg && (
              <span
                className={`text-sm ${saveMsg.ok ? "text-emerald-400" : "text-rose-400"}`}
              >
                {saveMsg.ok ? "✓ " : "✗ "}
                {saveMsg.text}
              </span>
            )}
          </div>

          {/* Run-now result */}
          {runNowMsg && (
            <p className="text-xs text-slate-400 bg-slate-900 rounded-lg
              px-4 py-2.5 border border-slate-800">
              {runNowMsg}
            </p>
          )}

        </div>
      </div>
    </main>
  );
}
