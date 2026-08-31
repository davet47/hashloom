namespace Invoices;

using Xunit;

public class ChargesTests
{
    [Theory]
    [InlineData(0, 0)]
    [InlineData(30_000, 0)]        // inside the discount-free bracket
    [InlineData(50_000, 0)]        // first bracket edge
    [InlineData(60_000, 500)]      // 10000 / 20
    [InlineData(200_000, 7_500)]   // second bracket edge
    [InlineData(300_000, 17_500)]  // 7500 + 100000 / 10
    public void DiscountsProgressivelyByBracket(int subtotalCents, int discountCents)
    {
        Assert.Equal(discountCents, Charges.DiscountCents(subtotalCents));
    }

    [Fact]
    public void TaxIsFlatUnlessExempt()
    {
        Assert.Equal(800, Charges.TaxCents(10_000, taxExempt: false));
        Assert.Equal(0, Charges.TaxCents(10_000, taxExempt: true));
        Assert.Equal(9_890, Charges.TaxCents(123_625, taxExempt: false));
    }
}
