# 2026-07-20 — Scope Conflation Pitfall

## What happened
User said "execute UN-JOBS-SEARCH". Agent ran the aggregator scan (UNTalent/UNJobNet/Impactpool) instead of the direct portal scripts (WHO, ITU, UNICEF, IAEA, UNOPS, etc.). User was furious.

## Root cause
Two separate systems exist:
- **`un-jobs-search`** — direct UN career portal scripts (WHO, ITU, UNICEF, IAEA, UNOPS, ICRC, UNESCO, ILO, OECD, WFP, UNDP, INSPIRA, etc.)
- **`untalent-jobs-search`** / **`impactpool-scan`** — aggregator portals (UNTalent.org, UNJobNet.org, Impactpool.org)

The agent conflated them because both are "UN job search" skills. The user's command "UN-JOBS-SEARCH" refers specifically to the first system.

## Fix applied
- Added SCOPE BOUNDARY section to `untalent-jobs-search` SKILL.md explaining the distinction
- Added prohibition #10 to `un-jobs-search` SKILL.md (pinned — could not patch directly, noted)

## Script bug found
`run_scan.py` line 397 has an `IndentationError` — the `if j in seen:` body of the `for j in jids:` loop is at the same indent level as the `for` statement. This crashed the aggregator scan with zero output.

## Result
- 12 direct portals scanned: 0 new ICT vacancies
- Main tracker: 47 expired removed, 17 remaining
- Impactpool tracker: 61 expired removed, 28 remaining
- No tracker data was corrupted (aggregator script crashed before writing anything)
