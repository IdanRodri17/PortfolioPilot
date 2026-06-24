/**
 * Currency-aware money formatting (V16).
 *
 * The backend tags each price/value with a currency — "USD" for US stocks and
 * crypto, "ILS" for TASE (".TA") holdings (agorot already normalized to
 * shekels). This renders ₪ vs $ accordingly. Falls back gracefully if the
 * runtime doesn't know a currency code.
 */
export function formatMoney(
  amount: number,
  currency: string = "USD",
  opts: { compact?: boolean } = {},
): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: opts.compact ? 0 : 2,
    }).format(amount);
  } catch {
    return `${amount}`;
  }
}

// User-selectable report base currency (V17). Report values are USD-canonical;
// this converts a USD amount to the chosen base for display only (percentages
// are unaffected). Falls back to USD if the ILS rate isn't available.
export type BaseCurrency = "USD" | "ILS";

export function displayMoney(
  usdAmount: number,
  base: BaseCurrency = "USD",
  ilsPerUsd: number | null = null,
  opts: { compact?: boolean } = {},
): string {
  if (base === "ILS" && ilsPerUsd) {
    return formatMoney(usdAmount * ilsPerUsd, "ILS", opts);
  }
  return formatMoney(usdAmount, "USD", opts);
}
