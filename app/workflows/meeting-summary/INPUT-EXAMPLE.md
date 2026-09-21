# meeting-summary - INPUT-EXAMPLE

Annotated example showing the input shape this workflow expects. Replace everything below with a real transcript when running.

```text
Meeting: Website relaunch sync
Date: 2026-09-20
Attendees: Anna (PM), Ben (Dev), Carla (Design)

Anna: The launch moves to October 3rd, marketing confirmed.
Ben: The contact form still throws a 500 on staging. I need two more days.
Carla: Homepage mockups are done, waiting on Anna's feedback.
Anna: Decision: we cut the blog migration from v1, it ships in v1.1.
Ben: I will fix the form by Friday and ping Carla for a retest.
```

Expected outputs for this input: `summary.md` (launch moved, form bug, blog cut), `actions.md` (Ben fixes form by Friday; Carla retests; Anna reviews mockups), `follow-up-email.md` (draft to all three).
