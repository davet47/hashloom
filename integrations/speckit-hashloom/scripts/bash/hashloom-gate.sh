#!/usr/bin/env bash
# hashloom-gate.sh — verify a feature's seams through the hashloom cache.
#
# Usage: hashloom-gate.sh <precheck|gate> [FEATURE_DIR]
#   FEATURE_DIR falls back to $FEATURE_DIR. Run from the project root:
#   hashloom resolves the project by walking up from the working directory.
#
# Reads FEATURE_DIR/seams.txt (one contract name per line; text after '#'
# and blank lines ignored), runs `hashloom index`, then
# `hashloom verify --radius` over the listed names, and prints exactly one
# JSON object on stdout:
#
#   {"ok": bool, "mode": "precheck"|"gate", "manifest": "...",
#    "seams": [names from the manifest],
#    "results": {"cached_pass": [...], "pass": [...],
#                "fail": [{"name","summary"}],
#                "error": [{"name","code","message"}]},
#    "spec_only": [manifest names with no impl — nothing to run],
#    "inferred": [...],          # only when non-empty: the review queue
#    "note": "..."}              # only on vacuous results
#
# Exit codes:
#   0  ok — including vacuous (missing/empty manifest) and every precheck
#      that reached a verdict (precheck never blocks on red)
#   1  gate mode only: verification failed (mirrors hashloom verify's ok bit)
#   2  infrastructure error (bad usage, hashloom/python3 missing, index
#      failed, unparseable verify output)

set -u

mode="${1:-}"
feature_dir="${2:-${FEATURE_DIR:-}}"

command -v python3 >/dev/null 2>&1 || {
  # not python3-rendered by definition; the message contains no user input
  echo '{"ok": false, "error": {"code": "python3_not_found", "message": "python3 is not on PATH"}}'
  exit 2
}

infra_error() { # $1 = code, $2 = message — JSON on stdout, exit 2
  python3 -c 'import json, sys; print(json.dumps(
      {"ok": False, "mode": sys.argv[1] or None,
       "error": {"code": sys.argv[2], "message": sys.argv[3]}}))' \
    "$mode" "$1" "$2"
  exit 2
}

vacuous_ok() { # $1 = note — JSON on stdout, exit 0
  python3 -c 'import json, sys; print(json.dumps(
      {"ok": True, "mode": sys.argv[1], "seams": [],
       "results": {"cached_pass": [], "pass": [], "fail": [], "error": []},
       "spec_only": [], "note": sys.argv[2]}))' \
    "$mode" "$1"
  exit 0
}

case "$mode" in
  precheck|gate) ;;
  *) infra_error usage "usage: hashloom-gate.sh <precheck|gate> [FEATURE_DIR]" ;;
esac
command -v hashloom >/dev/null 2>&1 \
  || infra_error hashloom_not_found "hashloom is not on PATH — pip install hashloom (or: uv tool install hashloom)"
[ -n "$feature_dir" ] \
  || infra_error no_feature_dir "no feature directory: pass it as the second argument or set FEATURE_DIR"
[ -d "$feature_dir" ] \
  || infra_error no_feature_dir "feature directory '$feature_dir' does not exist"

manifest="$feature_dir/seams.txt"
[ -f "$manifest" ] \
  || vacuous_ok "no seams manifest at $manifest — this feature declares no hashloom seams; nothing to gate"

seams=()
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%%#*}"                                  # strip comments
  line="${line#"${line%%[![:space:]]*}"}"             # ltrim
  line="${line%"${line##*[![:space:]]}"}"             # rtrim
  [ -n "$line" ] && seams+=("$line")
done < "$manifest"

[ "${#seams[@]}" -gt 0 ] \
  || vacuous_ok "seams manifest $manifest lists no names; nothing to gate"

# Re-index first: contracts edited during the session must reach the store
# before verify reads it. Index failure (invalid YAML, unknown dep, no
# .hashloom/ project) is infrastructure, not a verification verdict.
if ! index_err="$(hashloom index 2>&1 >/dev/null)"; then
  infra_error index_failed "hashloom index failed: ${index_err}"
fi

err_file="$(mktemp)"
trap 'rm -f "$err_file"' EXIT
verify_out="$(hashloom verify --radius "${seams[@]}" 2>"$err_file")"
verify_exit=$?
[ -n "$verify_out" ] \
  || infra_error verify_failed "hashloom verify produced no output (exit ${verify_exit}): $(cat "$err_file")"

if ! HASHLOOM_MODE="$mode" HASHLOOM_MANIFEST="$manifest" \
     python3 - "$verify_out" "${seams[@]}" <<'PY'
import json, os, sys

data = json.loads(sys.argv[1])
seams = sys.argv[2:]
buckets = {"cached_pass": [], "pass": [], "fail": [], "error": []}
inferred, seen = set(), set()
for r in data.get("results", []):
    name = r.get("name", "?")
    seen.add(name)
    status = r.get("status")
    if status == "cached-pass":
        buckets["cached_pass"].append(name)
    elif status == "pass":
        buckets["pass"].append(name)
    elif status == "fail":
        buckets["fail"].append({"name": name, "summary": r.get("summary", "")})
    else:  # "error": unknown contract, missing impl file, no_tests, ...
        err = r.get("error", {})
        buckets["error"].append({"name": name,
                                 "code": err.get("code", "error"),
                                 "message": err.get("message", "")})
    inferred.update(r.get("inferred", []))

out = {
    "ok": bool(data.get("ok", False)),
    "mode": os.environ["HASHLOOM_MODE"],
    "manifest": os.environ["HASHLOOM_MANIFEST"],
    "seams": seams,
    "results": buckets,
    # manifest names --radius dropped entirely: spec-only contracts (types)
    "spec_only": [n for n in seams if n not in seen],
}
if inferred:
    out["inferred"] = sorted(inferred)
print(json.dumps(out, indent=2))
PY
then
  infra_error verify_unparseable "could not parse hashloom verify output"
fi

if [ "$mode" = "gate" ]; then
  exit "$verify_exit"        # 0 green, 1 red — mirrors verify's ok bit
fi
exit 0                       # precheck never blocks
