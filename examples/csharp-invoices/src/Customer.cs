namespace Invoices;

/// <summary>Who gets billed; tax-exempt customers pay no tax at all.</summary>
public record Customer(string Id, string Name, bool TaxExempt);
