package ledger

import "testing"

func TestPostedEntries(t *testing.T) {
	entries := []Entry{
		{Account: "cash", Cents: 100, Debit: true, Posted: true},
		{Account: "cash", Cents: 200, Debit: true, Posted: false},
		{Account: "sales", Cents: 100, Debit: false, Posted: true},
	}
	got := PostedEntries(entries)
	if len(got) != 2 {
		t.Fatalf("got %d entries, want 2", len(got))
	}
	if got[0].Cents != 100 || got[1].Account != "sales" {
		t.Fatalf("order not preserved: %+v", got)
	}
	if len(PostedEntries(nil)) != 0 {
		t.Fatal("nil input must yield an empty slice")
	}
}
