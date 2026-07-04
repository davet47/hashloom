import type { LineItem } from "./types.ts";

// activeItems returns only the rows in the cart proper, preserving order.
// Saved-for-later rows are invisible to every total.
export function activeItems(items: LineItem[]): LineItem[] {
  return items.filter((i) => !i.savedForLater);
}
