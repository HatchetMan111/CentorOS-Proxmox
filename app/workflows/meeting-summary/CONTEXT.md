# meeting-summary - CONTEXT

## Purpose

Turns a raw meeting transcript into a cleaned summary, action items with owners, and a ready-to-send follow-up email.

## Contents

- `CONTEXT.md` - this file.
- `LOG.md` - append-only journal of actions and runs for this workflow.
- `INPUT-EXAMPLE.md` - annotated example transcript showing the expected input shape.

## Usage / Trigger Conditions

Run when [PRINCIPAL] says something like:

- "Summarize this meeting"
- "Run the meeting-summary workflow on this transcript"
- "Turn these meeting notes into action items"

Before running, [AI_NAME] confirms where the transcript comes from (pasted text or a file path). If the transcript is missing speaker names or decisions, [AI_NAME] asks [PRINCIPAL] instead of guessing.

## Inputs

- Raw meeting transcript (plain text, Markdown, or a `.txt`/`.md` file path).
- Optional: meeting date, attendee list, and desired output language.

## Outputs

- `summary.md` - short cleaned summary: context, key points, decisions.
- `actions.md` - action items as a checklist with owner and due date per item.
- `follow-up-email.md` - draft email to attendees with summary + actions.
- A `ran-complete` (or `ran-failed`) entry in this workflow's `LOG.md`.
- Dashboard page: `../../dashboard/workflows/meeting-summary/`.

## Steps

1. Read the transcript. If it is empty or unintelligible, stop and ask [PRINCIPAL] for a better source.
2. Extract: meeting goal, key discussion points, decisions made, open questions.
3. Derive action items. Every item needs an owner and (if stated or obvious) a due date. Never invent owners.
4. Write `summary.md`: 5-10 sentences max, facts only, no filler.
5. Write `actions.md`: `- [ ] <task> — Owner: <name>, Due: <date or "open">`.
6. Write `follow-up-email.md`: subject line, greeting, 3-bullet recap, action list, sign-off placeholder.
7. If a dashboard page was requested, ensure `../../dashboard/workflows/meeting-summary/index.html` exists (via `../../dashboard/create-dashboard-page.py`).
8. Append a `ran-complete` entry to `LOG.md` with input source and output paths.

## Dependencies

- **Runtime**: N/A (pure text workflow; any AI harness works).
- **Python packages**: N/A.
- **Node / npm packages**: N/A.
- **System binaries on PATH**: None.
- **API keys / env vars**: None.
- **Internal (CenterOS)**: None.
- **Dashboard (optional)**: `../../dashboard/`, `../../dashboard/create-dashboard-page.py`, `../../templates/dashboard-page/`.

## Known Issues / Gotchas

- Transcripts without speaker labels produce vague action items. Always ask for labels instead of assigning owners by guesswork.
- Very long transcripts (>30k words): summarize per agenda section first, then merge.

## Related

- `../../dashboard/workflows/meeting-summary/` - dashboard page for this workflow.
- `../../templates/workflow/` - template this workflow was scaffolded from.

## Revision History

- **2026-09-21** - Created. Shipped as a built-in example workflow.
