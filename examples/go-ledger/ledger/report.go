package ledger

import "fmt"

// Balanced reports whether the posted ledger balances: total debits equal
// total credits. An empty ledger is balanced.
func Balanced(entries []Entry) bool {
	return TotalDebits(entries) == TotalCredits(entries)
}

// FormatCents renders integer cents as a dollar string: 1234 -> "$12.34",
// -50 -> "-$0.50".
func FormatCents(cents int64) string {
	sign := ""
	if cents < 0 {
		sign, cents = "-", -cents
	}
	return fmt.Sprintf("%s$%d.%02d", sign, cents/100, cents%100)
}
