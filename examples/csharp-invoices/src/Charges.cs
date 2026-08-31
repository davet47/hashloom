namespace Invoices;

using System;

/// <summary>Volume discount and sales tax: progressive brackets over integer
/// cents, floored per bracket, so a bigger order never nets a smaller total.</summary>
public static class Charges
{
    internal const int DiscountFreeUpToCents = 50_000;
    internal const int SmallDiscountUpToCents = 200_000;
    internal const int TaxRatePercent = 8;

    /// <summary>Nothing to $500.00, 5% of the slice to $2,000.00, 10% above.</summary>
    public static int DiscountCents(int subtotalCents)
    {
        int discount = 0;
        if (subtotalCents > DiscountFreeUpToCents)
        {
            discount += (Math.Min(subtotalCents, SmallDiscountUpToCents) - DiscountFreeUpToCents) / 20;
        }
        if (subtotalCents > SmallDiscountUpToCents)
        {
            discount += (subtotalCents - SmallDiscountUpToCents) / 10;
        }
        return discount;
    }

    /// <summary>A flat 8% of the taxable amount, floored; exempt customers pay none.</summary>
    public static int TaxCents(int taxableCents, bool taxExempt)
    {
        return taxExempt ? 0 : taxableCents * TaxRatePercent / 100;
    }
}
