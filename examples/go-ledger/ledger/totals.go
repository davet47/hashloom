package ledger

// TotalDebits sums the cents of posted debit entries.
func TotalDebits(entries []Entry) int64 {
	var s int64
	for _, e := range PostedEntries(entries) {
		if e.Debit {
			s += e.Cents
		}
	}
	return s
}

// TotalCredits sums the cents of posted credit entries.
func TotalCredits(entries []Entry) int64 {
	var s int64
	for _, e := range PostedEntries(entries) {
		if !e.Debit {
			s += e.Cents
		}
	}
	return s
}

// BalanceByAccount maps each account to its posted balance: debits minus
// credits, in cents. Accounts with no posted entries are absent.
func BalanceByAccount(entries []Entry) map[Account]int64 {
	out := map[Account]int64{}
	for _, e := range PostedEntries(entries) {
		if e.Debit {
			out[e.Account] += e.Cents
		} else {
			out[e.Account] -= e.Cents
		}
	}
	return out
}
