import { test } from "node:test";
import assert from "node:assert";
import { activeItems } from "./filters.ts";
import type { LineItem } from "./types.ts";

test("activeItems drops saved-for-later rows and keeps order", () => {
  const items: LineItem[] = [
    { sku: "A", unitCents: 100, qty: 1, savedForLater: false },
    { sku: "B", unitCents: 200, qty: 1, savedForLater: true },
    { sku: "C", unitCents: 300, qty: 1, savedForLater: false },
  ];
  const got = activeItems(items);
  assert.deepStrictEqual(got.map((i) => i.sku), ["A", "C"]);
  assert.deepStrictEqual(activeItems([]), []);
});
