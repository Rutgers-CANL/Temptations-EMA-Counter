"""
counter_logic.py
----------------
Counts completed random surveys per participant from MetricWire's raw (API)
export. Pure functions, no UI -- app.py is the dashboard on top of this.

The problem this solves: MetricWire's own per-participant totals lump the
random surveys together with the urge assessments and the welcome survey,
and count partial submissions as completed. The raw export fixes both,
because every row carries a surveyId (which survey it is) and partial
submissions are marked in the answer cells themselves.

How a row is classified
-----------------------
1. WHICH SURVEY. Each row's surveyId decides it. The random survey's ID is
   known (KNOWN_RANDOM_SURVEY_IDS). Any other ID is recognized as the random
   survey if most of the questions it answers are random-survey questions
   (so a re-created copy of the same survey still works). Everything else --
   urge assessments, the welcome survey -- is "Other survey" and never
   counted. The dashboard shows what it found and lets a person override.

2. WHETHER IT'S COMPLETE (random-survey rows only):
     Empty     nothing was answered at all.
     Partial   at least one item is marked SKIPPED -- MetricWire's marker
               for "not reached because the participant exited early" -- or
               the very first question (urge_class_1) is unanswered.
     Complete  everything else.
   Only Complete counts toward the bonus.

   A blank cell does NOT make a survey partial. The duration questions
   (length_1 / length_2) come through blank in otherwise-complete surveys,
   so treating blank as "unanswered" would wrongly reject them. Only the
   explicit SKIPPED marker means "not reached."

3. DUPLICATES. A response (responseId) that appears in more than one file --
   overlapping exports -- is counted once, keeping the most recently updated
   copy.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

APP_DIR = Path(__file__).resolve().parent

KNOWN_RANDOM_SURVEY_IDS = {"684ae121721d4bb36f55940b"}
SKIPPED_TOKEN = "SKIPPED"
# Cell values that mean "no answer was given here". A real answer -- including
# the literal answer "None" (no urge) -- is anything not in this set.
NON_ANSWER_VALUES = {"", "NA", "CONDITION_SKIPPED", SKIPPED_TOKEN, "INFORMATION_QUESTION"}
ANCHOR_LABEL = "urge_class_1"          # the first question of the random survey
RANDOM_MATCH_THRESHOLD = 0.5           # share of answered questions that must be random-survey questions
RESPONSE_SUFFIX = ".response"
REQUIRED_COLUMNS = ["fname", "responseId", "surveyId", "ts_updated"]

STATUS_COMPLETE = "Complete"
STATUS_PARTIAL = "Partial"
STATUS_EMPTY = "Empty"
STATUS_NOT_RANDOM = "Not a random survey"
TYPE_RANDOM = "Random survey"
TYPE_OTHER = "Other survey"

_TEM_RE = re.compile(r"^TEM\d{4}$")


def load_question_map() -> dict[str, str]:
    """qid -> readable question name for the random survey."""
    return json.loads((APP_DIR / "random_survey_questions.json").read_text())


# ---------------------------------------------------------------------------
# Subject IDs
# ---------------------------------------------------------------------------

def normalize_subject_id(raw: str) -> str:
    """'tem19', 'TEM0019', ' 19 ' -> 'TEM0019'. Anything else is just
    upper-cased and stripped, so odd IDs (test accounts) stay recognizable."""
    s = str(raw).strip().upper()
    m = re.fullmatch(r"(?:TEM)?\s*0*(\d{1,4})", s)
    if m:
        return f"TEM{int(m.group(1)):04d}"
    return s


def parse_id_list(text: str) -> list[str]:
    """Pasted IDs separated by commas, spaces, semicolons or new lines,
    normalized and de-duplicated in the order given."""
    out: list[str] = []
    for tok in re.split(r"[,;\s]+", text or ""):
        if tok.strip():
            sid = normalize_subject_id(tok)
            if sid not in out:
                out.append(sid)
    return out


def looks_like_participant(subject_id: str) -> bool:
    return bool(_TEM_RE.match(subject_id))


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------

def read_export_files(files) -> tuple[pd.DataFrame, list[str]]:
    """Reads one or more raw-export files (.xlsx or .csv) into one table of
    strings. Everything is read as text with NA-detection OFF -- otherwise
    pandas silently turns the real answers "None" and "NA" into blanks.
    Returns (table, problems); a file that isn't a raw export is reported in
    problems and skipped rather than aborting the rest."""
    frames, problems = [], []
    for f in files:
        name = getattr(f, "name", str(f))
        try:
            if name.lower().endswith(".csv"):
                df = pd.read_csv(f, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8-sig")
            else:
                df = pd.read_excel(f, dtype=str, keep_default_na=False, na_filter=False)
        except Exception as e:  # noqa: BLE001 - surface any read failure to the user, per file
            problems.append(f"{name}: couldn't be read ({e}).")
            continue
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            problems.append(
                f"{name}: doesn't look like the raw (API) export -- missing column(s) "
                f"{', '.join(missing)}. This tool needs the raw export, not the Data Analysis tab."
            )
            continue
        df["_source_file"] = name
        frames.append(df)
    if not frames:
        return pd.DataFrame(), problems
    return pd.concat(frames, ignore_index=True, sort=False).fillna(""), problems


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _local_datetimes(df: pd.DataFrame) -> pd.Series:
    """Local time each survey was submitted: ts_updated (UTC epoch ms) plus
    the participant's own time-zone offset in minutes."""
    utc = pd.to_datetime(pd.to_numeric(df["ts_updated"], errors="coerce"), unit="ms", errors="coerce")
    if "time_zone_offset_minutes" in df.columns:
        offset = pd.to_numeric(df["time_zone_offset_minutes"], errors="coerce").fillna(0)
    else:
        offset = pd.Series(0, index=df.index)
    return utc + pd.to_timedelta(offset, unit="m")


def identify_surveys(df: pd.DataFrame, qmap: dict[str, str]) -> pd.DataFrame:
    """One row per surveyId: how many responses, how many subjects, how much
    of what it answers is random-survey content, and whether it's treated as
    the random survey (and why)."""
    qcols = [c for c in df.columns if c.endswith(RESPONSE_SUFFIX)]
    rows = []
    for sid, grp in df.groupby("surveyId", sort=False):
        answered = grp[qcols].apply(lambda col: ~col.isin(NON_ANSWER_VALUES)).any(axis=0)
        answered_qids = [c[: -len(RESPONSE_SUFFIX)] for c in answered.index[answered]]
        overlap = (sum(q in qmap for q in answered_qids) / len(answered_qids)) if answered_qids else 0.0
        if sid in KNOWN_RANDOM_SURVEY_IDS:
            is_random, why = True, "known random-survey ID"
        elif overlap >= RANDOM_MATCH_THRESHOLD:
            is_random, why = True, f"{overlap:.0%} of its questions are random-survey questions"
        else:
            is_random, why = False, f"only {overlap:.0%} of its questions are random-survey questions"
        rows.append({
            "surveyId": sid,
            "responses": len(grp),
            "subjects": grp["fname"].nunique(),
            "treated as": TYPE_RANDOM if is_random else TYPE_OTHER,
            "why": why,
        })
    return pd.DataFrame(rows)


def classify_responses(
    df: pd.DataFrame,
    qmap: dict[str, str],
    random_survey_ids: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Returns (responses, surveys_found, duplicates_removed).

    responses has one row per unique response with its survey type, status,
    and whether it counts. random_survey_ids overrides automatic detection
    when given (the dashboard's manual override)."""
    df = df.copy()
    for c in ("fname", "responseId", "surveyId"):
        df[c] = df[c].astype(str).str.strip()
    df["fname"] = df["fname"].map(normalize_subject_id)

    # Overlapping exports: one response, counted once -- the newest copy wins.
    before = len(df)
    df["_ts"] = pd.to_numeric(df["ts_updated"], errors="coerce")
    df = df.sort_values("_ts", kind="stable").drop_duplicates("responseId", keep="last").reset_index(drop=True)
    duplicates_removed = before - len(df)

    surveys = identify_surveys(df, qmap)
    if random_survey_ids is not None:
        surveys["treated as"] = surveys["surveyId"].map(lambda s: TYPE_RANDOM if s in random_survey_ids else TYPE_OTHER)
        surveys["why"] = surveys["surveyId"].map(lambda s: "chosen manually" if s in random_survey_ids else "not chosen")
    random_ids = set(surveys.loc[surveys["treated as"] == TYPE_RANDOM, "surveyId"])

    qcols = [c for c in df.columns if c.endswith(RESPONSE_SUFFIX)]
    vals = df[qcols]
    is_skipped = vals == SKIPPED_TOKEN
    is_answer = ~vals.isin(NON_ANSWER_VALUES)
    n_skipped = is_skipped.sum(axis=1)
    n_answered = is_answer.sum(axis=1)

    anchor_qid = next((q for q, lbl in qmap.items() if lbl == ANCHOR_LABEL), None)
    anchor_col = f"{anchor_qid}{RESPONSE_SUFFIX}" if anchor_qid else None
    if anchor_col in df.columns:
        anchor_ok = is_answer[anchor_col]
    else:  # survey version without that question: can't apply the check
        anchor_ok = pd.Series(True, index=df.index)

    labels = {c: qmap.get(c[: -len(RESPONSE_SUFFIX)], c[: -len(RESPONSE_SUFFIX)]) for c in qcols}
    skipped_items = pd.Series("", index=df.index)
    for i in df.index[n_skipped > 0]:
        skipped_items.at[i] = ", ".join(sorted(labels[c] for c in qcols if is_skipped.at[i, c]))

    is_random = df["surveyId"].isin(random_ids)
    status = pd.Series(STATUS_NOT_RANDOM, index=df.index)
    status[is_random & (n_answered == 0)] = STATUS_EMPTY
    status[is_random & (n_answered > 0) & ((n_skipped > 0) | ~anchor_ok)] = STATUS_PARTIAL
    status[is_random & (n_answered > 0) & (n_skipped == 0) & anchor_ok] = STATUS_COMPLETE

    reason = pd.Series("", index=df.index)
    reason[status == STATUS_EMPTY] = "no questions answered"
    reason[(status == STATUS_PARTIAL) & (n_skipped > 0)] = "items marked SKIPPED (exited early)"
    reason[(status == STATUS_PARTIAL) & (n_skipped == 0)] = "first question (urge_class_1) unanswered"
    reason[status == STATUS_NOT_RANDOM] = "not the random survey"

    responses = pd.DataFrame({
        "subject": df["fname"],
        "survey type": is_random.map({True: TYPE_RANDOM, False: TYPE_OTHER}),
        "survey ID": df["surveyId"],
        "status": status,
        "counts toward bonus": status == STATUS_COMPLETE,
        "why not counted": reason.where(status != STATUS_COMPLETE, ""),
        "items SKIPPED": n_skipped.astype(int),
        "skipped items": skipped_items,
        "submitted (local time)": _local_datetimes(df),
        "response ID": df["responseId"],
        "source file": df["_source_file"],
    })
    responses = responses.sort_values(["subject", "submitted (local time)"], kind="stable").reset_index(drop=True)
    return responses, surveys, duplicates_removed


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize(
    responses: pd.DataFrame,
    threshold: int,
    wanted_subjects: list[str] | None = None,
) -> pd.DataFrame:
    """One row per subject. A subject named in wanted_subjects who has no
    data in the files still gets a row (all zeros, flagged) rather than
    silently vanishing -- for payment, "no surveys found" and "not listed"
    are very different things."""
    rand = responses[responses["survey type"] == TYPE_RANDOM]
    g_all = responses.groupby("subject")
    summary = pd.DataFrame({
        "Completed random surveys": rand[rand["status"] == STATUS_COMPLETE].groupby("subject").size(),
        "Partial (not counted)": rand[rand["status"] == STATUS_PARTIAL].groupby("subject").size(),
        "Empty (not counted)": rand[rand["status"] == STATUS_EMPTY].groupby("subject").size(),
        "Other surveys (not counted)": responses[responses["survey type"] == TYPE_OTHER].groupby("subject").size(),
        "All responses": g_all.size(),
        "First survey": rand.groupby("subject")["submitted (local time)"].min().dt.date,
        "Last survey": rand.groupby("subject")["submitted (local time)"].max().dt.date,
    })
    if wanted_subjects is not None:
        summary = summary.reindex(wanted_subjects)
        summary["In files?"] = ["yes" if s in set(responses["subject"]) else "NO DATA FOUND" for s in summary.index]
    else:
        summary["In files?"] = "yes"
    count_cols = ["Completed random surveys", "Partial (not counted)", "Empty (not counted)",
                  "Other surveys (not counted)", "All responses"]
    summary[count_cols] = summary[count_cols].fillna(0).astype(int)
    summary.index.name = "Subject"
    summary = summary.reset_index()

    done = summary["Completed random surveys"]
    summary.insert(2, "Qualifies", done >= threshold)
    summary.insert(3, "Surveys to go", (threshold - done).clip(lower=0))
    return summary


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

def build_excel(summary: pd.DataFrame, responses: pd.DataFrame, notes: list[tuple[str, str]]) -> bytes:
    """Workbook with three sheets: Summary, every Responses row behind it, and
    About (the rules, threshold, files and data cutoff used). The About sheet
    is there so the file explains itself when someone opens it months later
    to answer "why was this person paid / not paid?"."""
    from io import BytesIO

    s = summary.copy()
    s["Qualifies"] = s["Qualifies"].map({True: "Yes", False: "No"})
    for c in ("First survey", "Last survey"):
        s[c] = s[c].astype(str).replace({"NaT": "", "nan": "", "None": ""})

    r = responses.copy()
    r["submitted (local time)"] = r["submitted (local time)"].dt.strftime("%Y-%m-%d %H:%M").fillna("")
    r["counts toward bonus"] = r["counts toward bonus"].map({True: "Yes", False: "No"})

    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        s.to_excel(xw, sheet_name="Summary", index=False)
        r.to_excel(xw, sheet_name="Responses", index=False)
        pd.DataFrame(notes).to_excel(xw, sheet_name="About", index=False, header=False)
        for name, frame in (("Summary", s), ("Responses", r), ("About", pd.DataFrame(notes))):
            ws = xw.book[name]
            for i, col in enumerate(frame.columns, start=1):
                longest = max([len(str(col))] + [len(str(v)) for v in frame[col].head(500)])
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max(longest + 2, 10), 70)
    return out.getvalue()
