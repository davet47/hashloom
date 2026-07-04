import type { LineItem } from "./types.ts";
import { activeItems } from "./filters.ts";

// subtotalCents sums unitCents * qty over the active rows.
export function subtotalCents(items: LineItem[]): number {
  return activeItems(items).reduce((s, i) => s + i.unitCents * i.qty, 0);
}

// itemCount sums the quantities of the active rows.
export function itemCount(items: LineItem[]): number {
  return activeItems(items).reduce((n, i) => n + i.qty, 0);
}
