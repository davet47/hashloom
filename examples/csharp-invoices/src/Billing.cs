namespace Invoices;

using System.Collections.Generic;
using System.Linq;

/// <summary>The billing run: one invoice per order, formatting, run totals.</summary>
public static class Billing
{
    /// <summary>The whole pipeline for one order: subtotal, discount, tax on
    /// what remains, all in one invoice.</summary>
    public static Invoice InvoiceFor(Customer customer, IReadOnlyList<LineItem> lines)
    {
        int subtotal = Pricing.SubtotalCents(lines);
        int discount = Charges.DiscountCents(subtotal);
        int tax = Charges.TaxCents(subtotal - discount, customer.TaxExempt);
        return new Invoice(customer.Id, subtotal, discount, tax, subtotal - discount + tax);
    }

    /// <summary>"$12.34" — dollars with exactly two cent digits; the minus sign leads.</summary>
    public static string FormatCents(int cents)
    {
        long abs = System.Math.Abs((long)cents);
        return (cents < 0 ? "-$" : "$") + (abs / 100) + "." + (abs % 100).ToString("D2");
    }

    /// <summary>One line per money field, all through FormatCents; ends with the total.</summary>
    public static string Render(Customer customer, Invoice invoice)
    {
        return customer.Name + " (" + invoice.CustomerId + ")\n"
            + "  subtotal " + FormatCents(invoice.SubtotalCents) + "\n"
            + "  discount " + FormatCents(invoice.DiscountCents) + "\n"
            + "  tax      " + FormatCents(invoice.TaxCents) + "\n"
            + "  total    " + FormatCents(invoice.TotalCents);
    }

    /// <summary>What the run bills in total; an empty run totals zero.</summary>
    public static int TotalBilledCents(IReadOnlyList<Invoice> invoices)
    {
        return invoices.Sum(i => i.TotalCents);
    }
}
