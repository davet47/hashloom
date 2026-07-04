// Sku identifies a product line by its stock-keeping unit.
export type Sku = string;

// LineItem is one row of a cart. Prices are integer cents so totals never
// accumulate float error; savedForLater rows are invisible to every total.
export interface LineItem {
  sku: Sku;
  unitCents: number;
  qty: number;
  savedForLater: boolean;
}
