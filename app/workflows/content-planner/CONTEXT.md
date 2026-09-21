# content-planner - CONTEXT

## Purpose

Turns one topic idea into a one-week content plan: angles, per-piece outlines, and a posting schedule for blog and social channels.

## Contents

- `CONTEXT.md` - this file.
- `LOG.md` - append-only journal of actions and runs for this workflow.

## Usage / Trigger Conditions

Run when [PRINCIPAL] says something like:

- "Plan content around X"
- "Run the content-planner workflow for <topic>"
- "I need a week of posts about Y"

Before running, [AI_NAME] confirms two things with [PRINCIPAL]:

1. **Channels** - e.g. blog, LinkedIn, X. Default: blog + LinkedIn.
2. **Voice** - one sentence on tone (e.g. "practical, no hype") or a pointer to an existing piece to match.

## Inputs

- Topic idea (one sentence).
- Channels (default: blog + LinkedIn).
- Voice note (default: practical, no hype).
- Optional: cadence (default: 1 blog post + 3 social posts across one week).

## Outputs

- `plan.md` with:
  1. **Angles** - 3 distinct angles on the topic, one line each.
  2. **Pieces** - per piece: channel, working title, 5-bullet outline, CTA.
  3. **Schedule** - day-by-day posting plan for one week.
- A `ran-complete` (or `ran-failed`) entry in this workflow's `LOG.md`.
- Dashboard page: `../../dashboard/workflows/content-planner/`.

## Steps

1. Confirm channels and voice with [PRINCIPAL] if not provided.
2. Draft 3 angles that do not overlap. Kill the weakest if two are too similar.
3. Expand each surviving angle into pieces per the cadence: working title + 5-bullet outline + CTA.
4. Lay out the week: no two days with the same channel back-to-back unless [PRINCIPAL] asks.
5. Write `plan.md`.
6. If a dashboard page was requested, ensure `../../dashboard/workflows/content-planner/index.html` exists (via `../../dashboard/create-dashboard-page.py`).
7. Append a `ran-complete` entry to `LOG.md` with topic, channels, and piece count.

## Dependencies

- **Runtime**: N/A (pure text workflow; any AI harness works).
- **Python packages**: N/A.
- **Node / npm packages**: N/A.
- **System binaries on PATH**: None.
- **API keys / env vars**: None.
- **Internal (CenterOS)**: None.
- **Dashboard (optional)**: `../../dashboard/`, `../../dashboard/create-dashboard-page.py`, `../../templates/dashboard-page/`.

## Known Issues / Gotchas

- Generic angles ("5 tips for X") are the default failure mode. Force each angle to take a stance or name a tradeoff.
- Keep outlines at 5 bullets; longer outlines do not get written.

## Related

- `../../dashboard/workflows/content-planner/` - dashboard page for this workflow.
- `../../templates/workflow/` - template this workflow was scaffolded from.

## Revision History

- **2026-09-21** - Created. Shipped as a built-in example workflow.
