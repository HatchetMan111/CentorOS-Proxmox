# research-brief - CONTEXT

## Purpose

Turns a topic plus a stated question into a short, source-grounded research brief: answer first, evidence second, gaps flagged honestly.

## Contents

- `CONTEXT.md` - this file.
- `LOG.md` - append-only journal of actions and runs for this workflow.

## Usage / Trigger Conditions

Run when [PRINCIPAL] says something like:

- "Research X for me"
- "Run the research-brief workflow on <topic>"
- "Give me a briefing on Y before my call"

Before running, [AI_NAME] confirms two things with [PRINCIPAL]:

1. **The exact question** to answer (one sentence).
2. **Depth**: quick (5 minutes, 3-5 sources) or deep (named sources, counter-arguments).

## Inputs

- Topic and one-sentence research question.
- Depth: `quick` (default) or `deep`.
- Optional: sources to include or exclude, target audience, output language.

## Outputs

- `brief.md` with this structure:
  1. **Bottom line** - the answer in 2-3 sentences.
  2. **Evidence** - key facts, each with its source.
  3. **Counterpoints** - what speaks against the bottom line (deep mode only).
  4. **Gaps** - what could not be verified.
  5. **Sources** - link list.
- A `ran-complete` (or `ran-failed`) entry in this workflow's `LOG.md`.
- Dashboard page: `../../dashboard/workflows/research-brief/`.

## Steps

1. Restate the research question back to [PRINCIPAL] if it is ambiguous. Do not start on a vague question.
2. Collect sources. Prefer primary sources (docs, papers, official announcements) over aggregators.
3. Write the bottom line first, then the evidence that supports it.
4. Mark every claim that lacks a source explicitly as unverified. Never present unverified claims as facts.
5. In deep mode, add counterpoints: the strongest two arguments against the bottom line.
6. Write `brief.md` and list all sources with links.
7. If a dashboard page was requested, ensure `../../dashboard/workflows/research-brief/index.html` exists (via `../../dashboard/create-dashboard-page.py`).
8. Append a `ran-complete` entry to `LOG.md` with question, depth, and source count.

## Dependencies

- **Runtime**: N/A (pure text workflow; web search capability of the harness is used when available).
- **Python packages**: N/A.
- **Node / npm packages**: N/A.
- **System binaries on PATH**: None.
- **API keys / env vars**: None.
- **Internal (CenterOS)**: None.
- **Dashboard (optional)**: `../../dashboard/`, `../../dashboard/create-dashboard-page.py`, `../../templates/dashboard-page/`.

## Known Issues / Gotchas

- Without web access the harness must say so up front and work only from provided sources. Never fake sources or links.
- Quick mode is capped at 3-5 sources; say so if the question needs more.

## Related

- `../../dashboard/workflows/research-brief/` - dashboard page for this workflow.
- `../../templates/workflow/` - template this workflow was scaffolded from.

## Revision History

- **2026-09-21** - Created. Shipped as a built-in example workflow.
