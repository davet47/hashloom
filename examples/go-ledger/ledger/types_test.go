package ledger

import "testing"

func TestAccount(t *testing.T) {
	a := Account("cash")
	if string(a) != "cash" {
		t.Fatalf("got %q, want %q", a, "cash")
	}
}

func TestEntry(t *testing.T) {
	e := Entry{Account: "cash", Cents: 1250, Debit: true, Posted: true}
	if e.Account != "cash" || e.Cents != 1250 || !e.Debit || !e.Posted {
		t.Fatalf("field order or zero values changed: %+v", e)
	}
	var zero Entry
	if zero.Posted {
		t.Fatal("a zero Entry must not count as posted")
	}
}
