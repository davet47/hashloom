package ledger

import "testing"

var fixture = []Entry{
	{Account: "cash", Cents: 1000, Debit: true, Posted: true},
	{Account: "sales", Cents: 1000, Debit: false, Posted: true},
	{Account: "cash", Cents: 250, Debit: true, Posted: true},
	{Account: "sales", Cents: 250, Debit: false, Posted: true},
	{Account: "cash", Cents: 9999, Debit: true, Posted: false}, // unposted: invisible
}

func TestTotalDebits(t *testing.T) {
	if got := TotalDebits(fixture); got != 1250 {
		t.Fatalf("got %d, want 1250", got)
	}
}

func TestTotalCredits(t *testing.T) {
	if got := TotalCredits(fixture); got != 1250 {
		t.Fatalf("got %d, want 1250", got)
	}
}

func TestBalanceByAccount(t *testing.T) {
	got := BalanceByAccount(fixture)
	if got["cash"] != 1250 || got["sales"] != -1250 {
		t.Fatalf("got %+v, want cash=1250 sales=-1250", got)
	}
	if _, ok := got["ghost"]; ok {
		t.Fatal("accounts with no posted entries must be absent")
	}
}
