import { test } from "node:test";
import assert from "node:assert";
import type { Sku, LineItem } from "./types.ts";

test("Sku is a plain string id", () => {
  const s: Sku = "WIDGET-1";
  assert.strictEqual(s, "WIDGET-1");
});

test("LineItem carries sku, unitCents, qty, savedForLater", () => {
  const i: LineItem = { sku: "WIDGET-1", unitCents: 1250, qty: 2, savedForLater: false };
  assert.strictEqual(i.unitCents, 1250);
  assert.strictEqual(i.qty, 2);
  assert.strictEqual(i.savedForLater, false);
});
