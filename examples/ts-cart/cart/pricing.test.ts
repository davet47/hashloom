import { test } from "node:test";
import assert from "node:assert";
import { discountCents, totalCents, formatPrice } from "./pricing.ts";
import type { LineItem } from "./types.ts";

test("discountCents floors in the customer's favour", () => {
  assert.strictEqual(discountCents(999, 10), 99); // 99.9 floors to 99
  assert.strictEqual(discountCents(1000, 0), 0);
  assert.strictEqual(discountCents(1000, 100), 1000);
});

test("totalCents applies the discount to the active subtotal", () => {
  const items: LineItem[] = [
    { sku: "A", unitCents: 1000, qty: 2, savedForLater: false },
    { sku: "B", unitCents: 9999, qty: 1, savedForLater: true },
  ];
  assert.strictEqual(totalCents(items, 10), 1800);
  assert.strictEqual(totalCents(items, 0), 2000);
});

test("formatPrice renders cents as dollars", () => {
  assert.strictEqual(formatPrice(1234), "$12.34");
  assert.strictEqual(formatPrice(5), "$0.05");
  assert.strictEqual(formatPrice(0), "$0.00");
  assert.strictEqual(formatPrice(-50), "-$0.50");
});
