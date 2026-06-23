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
