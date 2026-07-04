package ledger

// PostedEntries returns only the entries that have been posted, preserving
// order. Unposted entries are invisible to every aggregate.
func PostedEntries(entries []Entry) []Entry {
	out := make([]Entry, 0, len(entries))
	for _, e := range entries {
		if e.Posted {
			out = append(out, e)
		}
	}
	return out
}
