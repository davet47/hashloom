package ledger

import "testing"

func TestBalanced(t *testing.T) {
	if !Balanced(fixture) {
		t.Fatal("fixture ledger must balance")
	}
	if !Balanced(nil) {
		t.Fatal("an empty ledger is balanced")
	}
	lopsided := append([]Entry{}, fixture...)
	lopsided = append(lopsided, Entry{Account: "cash", Cents: 1, Debit: true, Posted: true})
	if Balanced(lopsided) {
		t.Fatal("an extra posted debit must unbalance the ledger")
	}
}

func TestFormatCents(t *testing.T) {
	cases := map[int64]string{1234: "$12.34", 5: "$0.05", 0: "$0.00", -50: "-$0.50"}
	for cents, want := range cases {
		if got := FormatCents(cents); got != want {
			t.Fatalf("FormatCents(%d) = %q, want %q", cents, got, want)
		}
	}
}
