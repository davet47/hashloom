namespace Invoices;

using Xunit;

public class PricingTests
{
    [Fact]
    public void LineTotalMultipliesQuantityByUnitPrice()
    {
        Assert.Equal(7500, Pricing.LineTotalCents(new LineItem("WIDGET", 3, 2500)));
        Assert.Equal(0, Pricing.LineTotalCents(new LineItem("WIDGET", 0, 2500)));
    }

    [Fact]
    public void SubtotalSumsEveryLine()
    {
        var lines = new[]
        {
            new LineItem("WIDGET", 3, 2500),
            new LineItem("GADGET", 10, 12000),
        };
        Assert.Equal(127500, Pricing.SubtotalCents(lines));
        Assert.Equal(0, Pricing.SubtotalCents(System.Array.Empty<LineItem>()));
    }
}
