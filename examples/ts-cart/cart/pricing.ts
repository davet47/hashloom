import type { LineItem } from "./types.ts";
import { subtotalCents } from "./totals.ts";

// discountCents converts a percentage discount to cents off, rounding down so
// the customer is never charged a fractional cent in their favour.
export function discountCents(cents: number, percent: number): number {
  return Math.floor((cents * percent) / 100);
}

// totalCents is the active subtotal minus the discount.
export function totalCents(items: LineItem[], discountPercent: number): number {
  const sub = subtotalCents(items);
  return sub - discountCents(sub, discountPercent);
}

// formatPrice renders integer cents as a dollar string: 1234 -> "$12.34",
// -50 -> "-$0.50".
export function formatPrice(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const dollars = Math.trunc(abs / 100);
  const rem = String(abs % 100).padStart(2, "0");
  return `${sign}$${dollars}.${rem}`;
}
