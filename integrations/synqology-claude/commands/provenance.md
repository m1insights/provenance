---
description: Open, audit and notify on Provenance's agent-written pull requests
---

Run the Provenance operator loop. Everything below is idempotent — running it
twice must not audit anything twice or send a duplicate email.

## 1. Open pull requests for findings that have none

```
.venv/bin/python -m provenance engineer
```

Skip this step if it reports "no open findings to engineer". It only opens
pull requests for findings that do not already have one.

## 2. Find what needs auditing

For both `m1insights/synq` and `m1insights/synq_insights`, list open pull
requests whose head branch starts with `provenance/`:

```
gh pr list --repo m1insights/synq --state open --json number,title,headRefName
gh pr list --repo m1insights/synq_insights --state open --json number,title,headRefName
```

For each, read its comments and skip any already containing the marker
`<!-- opus-audit -->`:

```
gh pr view <n> --repo <repo> --json comments --jq '.comments[].body' | grep -c 'opus-audit'
```

If nothing is unaudited, say so in one line and stop. Do not send email, do not
post anything.

## 3. Audit each unaudited pull request

Use the **provenance-audit** skill. Invoke it with the Skill tool — it carries
the full review brief and this repository's real bug history.

Read the diff with `gh pr diff <n> --repo <repo>`, and read
`/Users/m1labs/Dev/apps/synqology/CLAUDE.md` explicitly — it sits above the
`synq` repo and a session inside it will not pick the conventions up.

Show your reasoning as you go. The founder is watching this happen in the
terminal; that visibility is the point of the command existing.

## 4. Post each audit to its pull request

```
gh pr comment <n> --repo <repo> --body "<!-- opus-audit -->
## Independent review — Opus, <date>

**Verdict: CLEAN | CONCERNS | DEFECT**

<one-sentence summary>

<findings: what, why it matters, what to do>

---
Reviewed by Claude Opus against \`apps/synqology/CLAUDE.md\` and this
repository's bug history. Gemini wrote this change; this is the independent
check before a human decides. No agent can merge it."
```

The marker comment is the memory — it is how the session hook and a later run
of this command know the audit already happened.

## 5. Send one decision email per newly audited pull request

```
cd /Users/m1labs/Dev/provenance && .venv/bin/python -m provenance notify --pr <n> --repo <repo> --verdict <verdict> --summary "<one line>"
```

Only for pull requests audited in *this* run. The email carries the verdict, so
the founder decides already knowing what the audit found.

## 6. Summarise

Print, in a few lines: what was opened, what was audited, each verdict, and
what is now waiting on a decision. If a verdict was DEFECT, say plainly that
the change should not be merged as written and why.
