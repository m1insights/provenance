#!/usr/bin/env bash
# Session-start check for un-audited agent-written pull requests.
#
# Three properties this must hold, in order of importance:
#
#   1. It can never stop a session starting. Every failure path exits 0 with no
#      output — no token, no network, no gh, malformed JSON, anything.
#   2. It is silent when there is nothing. A hook that speaks every session is
#      a hook that gets ignored, and then it is worse than absent.
#   3. It is fast. Hard timeouts on every network call; a slow morning must not
#      become a slow terminal.
#
# The marker `<!-- opus-audit -->` in a pull request comment is the memory: it
# is how this knows an audit already happened, with no state stored anywhere.

set -uo pipefail

REPOS=("m1insights/synq" "m1insights/synq_insights")
MARKER="opus-audit"
CURL_TIMEOUT=4

# Any failure from here is silence, never noise.
trap 'exit 0' ERR

command -v gh >/dev/null 2>&1 || exit 0
TOKEN="$(gh auth token 2>/dev/null)" || exit 0
[ -n "${TOKEN:-}" ] || exit 0

api() {
  curl -sS --max-time "$CURL_TIMEOUT" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/$1" 2>/dev/null || true
}

pending=""

for repo in "${REPOS[@]}"; do
  pulls="$(api "repos/${repo}/pulls?state=open&per_page=50")"
  [ -n "$pulls" ] || continue

  # Only provenance branches. jq absent or JSON malformed -> empty -> skipped.
  rows="$(printf '%s' "$pulls" \
    | jq -r '.[]? | select(.head.ref | startswith("provenance/"))
             | "\(.number)\t\(.title)"' 2>/dev/null)" || continue
  [ -n "$rows" ] || continue

  while IFS=$'\t' read -r number title; do
    [ -n "$number" ] || continue
    comments="$(api "repos/${repo}/issues/${number}/comments?per_page=100")"
    if printf '%s' "$comments" | grep -q "$MARKER" 2>/dev/null; then
      continue   # already audited
    fi
    pending="${pending}  ${repo}#${number} — ${title}"$'\n'
  done <<< "$rows"
done

[ -n "$pending" ] || exit 0

cat <<EOF
Un-audited agent-written pull requests are open:

${pending}
These were written by Gemini from research evidence, with no human or
independent model review yet. Run /provenance to audit them before other work,
unless the user asks for something else first.
EOF
exit 0
