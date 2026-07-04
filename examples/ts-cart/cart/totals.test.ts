import { test } from "node:test";
import assert from "node:assert";
import { subtotalCents, itemCount } from "./totals.ts";
import type { LineItem } from "./types.ts";

const fixture: LineItem[] = [
  { sku: "A", unitCents: 1000, qty: 2, savedForLater: false },
  { sku: "B", unitCents: 250, qty: 1, savedForLater: false },
  { sku: "C", unitCents: 9999, qty: 3, savedForLater: true }, // saved: invisible
];

test("subtotalCents sums unitCents times qty over active rows", () => {
  assert.strictEqual(subtotalCents(fixture), 2250);
  assert.strictEqual(subtotalCents([]), 0);
});

test("itemCount sums quantities of active rows", () => {
  assert.strictEqual(itemCount(fixture), 3);
  assert.strictEqual(itemCount([]), 0);
});
