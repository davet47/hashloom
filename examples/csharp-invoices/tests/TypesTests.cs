namespace Invoices;

using Xunit;

public class TypesTests
{
    [Fact]
    public void CustomerCarriesTaxExemption()
    {
        var ada = new Customer("c1", "Ada Lovelace", TaxExempt: false);
        Assert.False(ada.TaxExempt);
        Assert.Equal(ada, new Customer("c1", "Ada Lovelace", false));
    }

    [Fact]
    public void LineItemHoldsIntegerCents()
    {
        var line = new LineItem("WIDGET", Quantity: 3, UnitCents: 2500);
        Assert.Equal(2500, line.UnitCents);
        Assert.Equal(line, new LineItem("WIDGET", 3, 2500));
    }

    [Fact]
    public void InvoiceIsEqualByFields()
    {
        var a = new Invoice("c1", 127500, 3875, 9890, 133515);
        Assert.Equal(a, new Invoice("c1", 127500, 3875, 9890, 133515));
        Assert.Equal(a.SubtotalCents - a.DiscountCents + a.TaxCents, a.TotalCents);
    }
}
