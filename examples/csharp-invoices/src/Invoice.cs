namespace Invoices;

/// <summary>The billed result: total = subtotal - discount + tax, always.</summary>
public record Invoice(
    string CustomerId, int SubtotalCents, int DiscountCents, int TaxCents, int TotalCents);
