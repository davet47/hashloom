package ledger

// Account identifies a ledger account by name.
type Account string

// Entry is one side of a double-entry posting. Amounts are integer cents so
// totals never accumulate float error; Posted entries are the only ones any
// aggregate counts.
type Entry struct {
	Account Account
	Cents   int64
	Debit   bool
	Posted  bool
}
