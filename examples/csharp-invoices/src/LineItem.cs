namespace Invoices;

/// <summary>One ordered position. Money is integer cents everywhere in this
/// project — no decimals or doubles touch currency.</summary>
public record LineItem(string Sku, int Quantity, int UnitCents);
