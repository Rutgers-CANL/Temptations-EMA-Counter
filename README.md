# EMA Survey Counter

Counts **completed random surveys** per participant from MetricWire's raw
(API) export, so it's clear who has reached the bonus threshold (38 by
default).

MetricWire's own totals can't be used for this: they lump the random
surveys together with the urge assessments and the welcome survey, and they
count partial submissions as completed. This tool separates all of that out
and shows its work.

## Using it

1. **Double-click `launch.py`.** The first run takes a minute or two to set
   itself up; after that it opens in your browser quickly. Leave the black
   window open while you use it.
2. **Drop in the raw export file(s)** -- the same raw (API) export the EMA
   uploader uses. One file per participant or one for everyone, any
   number of files; files that overlap are fine (nothing is counted twice).
3. **Paste the IDs you're paying** into the box (commas, spaces or new
   lines; `TEM0019`, `tem19` and `19` all work). Leave it blank to see
   everyone.

Read the **Completed** column: that's the number that counts toward the
bonus, with a status of "Qualifies" or how many surveys are still to go.
The columns beside it explain any gap from MetricWire's total (partial
surveys, empty surveys, other surveys).

To explain one person's number, pick them under **"Look at one
participant's responses"** -- it lists every response, whether it counted,
and why not. **Download Excel** gives a workbook with the summary, every
response behind it, and a notes sheet recording the rules, threshold, files
and data cutoff used -- so the file still explains itself later.

**Check the date above the table.** Counts are only as current as the
export; it shows the latest survey included.

## How a survey is counted

- **Which survey:** each row's survey ID says which survey it is. Only the
  random survey counts; urge assessments and the welcome survey never do.
  The random survey's ID is built in, and any other ID whose questions are
  mostly random-survey questions is recognized as the random survey too (so a
  re-created copy still works). Expand **"Surveys found in these files"** to
  see what was detected, and override it there if it's ever wrong.
- **Complete:** no items marked `SKIPPED` -- MetricWire's marker for "not
  reached because the participant exited early" -- and the first question was
  answered. Only these count.
- **Partial:** at least one item is `SKIPPED`. Not counted.
- **Empty:** nothing answered at all. Not counted.
- **Blank cells don't make a survey partial.** The duration questions come
  through blank in otherwise-complete surveys, so only the explicit
  `SKIPPED` marker means "not reached."
- **Duplicates:** a response in more than one file is counted once.
- IDs that don't look like `TEM####` (test accounts) are hidden by default;
  a sidebar checkbox shows them.
- A pasted ID with no data in the files shows **"No data found"** rather than
  disappearing -- that means "not in these files," not necessarily "did no
  surveys."

## Decisions worth confirming with the PI

These change who qualifies, so they shouldn't be left to default:

1. **Partials don't count at all.** Any survey with a `SKIPPED` item is
   excluded from the bonus count -- including one that finished the first
   urge set. (The EMA *uploader* does upload those, per the PI's rule for
   REDCap data, but that's a data question, not necessarily a payment one.)
   If partials that finished a full urge set should count toward the bonus,
   that can be added.
2. **"Any `SKIPPED`" is strict.** A participant who answered every question
   but exited before the final screen would show as partial. The per-person
   view lists exactly which items were skipped, so a borderline case can be
   judged by a person rather than the rule.
3. **No date window.** Everything in the uploaded files counts, from the first
   survey on.

## Limitations

- **Tested against a random-survey-only raw export.** The only real file
  available while building this contained random surveys only. Telling the
  random survey apart from the urge assessment and welcome survey was tested
  on synthetic data built from real rows. The first time you load a real
  export that includes those surveys, glance at **"Surveys found in these
  files"** to confirm it sorted them correctly.
- Needs the **raw (API) export**. The Data Analysis tab export has no survey
  ID, so it can't be used; the tool says so if you try.
- If the random survey is ever rebuilt in MetricWire, its question IDs change.
  Update `KNOWN_RANDOM_SURVEY_IDS` in `counter_logic.py` and regenerate
  `random_survey_questions.json` from the new config -- or just use the manual
  override above, which needs no code change.

## Files

- `app.py` -- the dashboard
- `counter_logic.py` -- all the counting rules (no UI; testable on its own)
- `random_survey_questions.json` -- question ID -> name for the random survey
- `launch.py` -- double-click launcher (private environment, separate from the
  EMA uploader's)
- `requirements.txt`
