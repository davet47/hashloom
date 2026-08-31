namespace Invoices;

using System.Collections.Generic;
using System.Linq;

/// <summary>Line and order arithmetic over integer cents.</summary>
public static class Pricing
{
    /// <summary>Quantity times unit price; a zero quantity totals zero.</summary>
    public static int LineTotalCents(LineItem line)
    {
        return line.Quantity * line.UnitCents;
    }

    /// <summary>The sum of every line total; an empty order subtotals zero.</summary>
    public static int SubtotalCents(IReadOnlyList<LineItem> lines)
    {
        return lines.Sum(LineTotalCents);
    }
}
