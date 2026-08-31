namespace Invoices;

using Xunit;

public class BillingTests
{
    static readonly Customer Ada = new("c1", "Ada Lovelace", TaxExempt: false);

    static readonly LineItem[] Order =
    {
        new("WIDGET", 3, 2500),
        new("GADGET", 10, 12000),
    };

    [Fact]
    public void InvoiceRunsTheWholePipeline()
    {
        Assert.Equal(
            new Invoice("c1", 127500, 3875, 9890, 133515),
            Billing.InvoiceFor(Ada, Order));
    }

    [Fact]
    public void TotalBilledSumsInvoices()
    {
        var run = new[]
        {
            Billing.InvoiceFor(Ada, Order),
            new Invoice("c2", 100, 0, 8, 108),
        };
        Assert.Equal(133_623, Billing.TotalBilledCents(run));
        Assert.Equal(0, Billing.TotalBilledCents(System.Array.Empty<Invoice>()));
    }

    public class Formatting
    {
        [Fact]
        public void FormatsCentsAsDollars()
        {
            Assert.Equal("$1335.15", Billing.FormatCents(133_515));
            Assert.Equal("$0.05", Billing.FormatCents(5));
            Assert.Equal("-$0.50", Billing.FormatCents(-50));
        }

        [Fact]
        public void RendersOneLinePerMoneyField()
        {
            var text = Billing.Render(Ada, Billing.InvoiceFor(Ada, Order));
            Assert.Equal(
                "Ada Lovelace (c1)\n"
                + "  subtotal $1275.00\n"
                + "  discount $38.75\n"
                + "  tax      $98.90\n"
                + "  total    $1335.15",
                text);
        }
    }
}
