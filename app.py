"""
EMA Survey Counter
------------------
Counts completed random surveys per participant from MetricWire raw (API)
export files, for working out who qualifies for the completion bonus.

Run with:  streamlit run app.py   (or double-click launch.py)
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

import counter_logic as C

st.set_page_config(page_title="EMA Survey Counter", layout="wide")

DEFAULT_THRESHOLD = 38

RULES_TEXT = [
    "Only the RANDOM survey counts. Urge assessments and the welcome survey are told apart by their "
    "survey ID and are never counted.",
    "A random survey counts only if it is COMPLETE: no items marked SKIPPED (MetricWire's marker for "
    "'not reached because the participant exited early') and the first question was answered.",
    "Partial surveys (any SKIPPED item) and empty surveys (nothing answered) are NOT counted. They're "
    "listed per participant so the difference from MetricWire's own total is explained.",
    "A blank cell by itself does NOT make a survey partial -- the duration questions come through blank "
    "in otherwise-complete surveys.",
    "A response that appears in more than one file is counted once (newest copy kept).",
    "Counts are only as current as the export: they cover responses up to the date shown above the table.",
]


@st.cache_data(show_spinner="Reading files...")
def load_and_classify(payload: tuple, random_override: tuple | None):
    """payload is ((filename, bytes), ...) so the work is cached on the file
    contents and doesn't rerun every time a widget is touched."""
    files = []
    for name, data in payload:
        buf = io.BytesIO(data)
        buf.name = name
        files.append(buf)
    df, problems = C.read_export_files(files)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), 0, problems, 0
    qmap = C.load_question_map()
    override = set(random_override) if random_override is not None else None
    responses, surveys, dups = C.classify_responses(df, qmap, random_survey_ids=override)
    return responses, surveys, dups, problems, len(df)


def status_text(row) -> str:
    if row["In files?"] != "yes":
        return "No data found"
    return "\u2705 Qualifies" if row["Qualifies"] else f"\u23f3 {row['Surveys to go']} to go"


def main():
    st.title("EMA Survey Counter")
    st.caption("Counts completed random surveys per participant from MetricWire raw exports.")

    with st.sidebar:
        st.header("Settings")
        threshold = st.number_input(
            "Completed random surveys needed for the bonus", min_value=1, max_value=500, value=DEFAULT_THRESHOLD, step=1
        )
        show_nonparticipant = st.checkbox(
            "Include IDs that don't look like TEM####",
            value=False,
            help="Test accounts and other non-participant IDs are hidden by default.",
        )

    with st.expander("How surveys are counted", expanded=False):
        for line in RULES_TEXT:
            st.markdown(f"- {line}")

    files = st.file_uploader(
        "Drop the raw export file(s) here (.xlsx or .csv) -- one file per participant or one for everyone; "
        "overlapping files are fine.",
        type=["xlsx", "csv"],
        accept_multiple_files=True,
    )
    if not files:
        st.info("Upload one or more raw (API) export files to get started.")
        return

    payload = tuple((f.name, f.getvalue()) for f in files)
    responses, surveys, dups, problems, n_rows = load_and_classify(payload, None)
    for p in problems:
        st.warning(p)
    if responses.empty:
        st.error("None of the uploaded files could be used.")
        return

    # --- which survey is the random survey ---------------------------------
    detected = tuple(sorted(surveys.loc[surveys["treated as"] == C.TYPE_RANDOM, "surveyId"]))
    with st.expander(f"Surveys found in these files ({len(surveys)})", expanded=not detected):
        st.dataframe(surveys, hide_index=True, width="stretch")
        chosen = st.multiselect(
            "Treat these survey IDs as the random survey",
            options=list(surveys["surveyId"]),
            default=list(detected),
            help="Normally detected automatically. Change this only if the wrong survey was picked.",
        )
    if tuple(sorted(chosen)) != detected:
        responses, surveys, dups, problems, n_rows = load_and_classify(payload, tuple(sorted(chosen)))
    if not chosen:
        st.error(
            "No random survey was recognized in these files. Open 'Surveys found in these files' above "
            "and choose which survey ID is the random survey."
        )
        return

    # --- hide non-participant IDs -------------------------------------------
    non_participant = sorted({s for s in responses["subject"] if not C.looks_like_participant(s)})
    if non_participant and not show_nonparticipant:
        responses = responses[responses["subject"].map(C.looks_like_participant)]
        st.caption(
            f"Hiding {len(non_participant)} ID(s) that don't look like TEM#### "
            f"({', '.join(non_participant[:8])}{'...' if len(non_participant) > 8 else ''}). "
            "Turn this on in the sidebar to include them."
        )
    if responses.empty:
        st.error("No participant data left after hiding non-participant IDs.")
        return

    rand = responses[responses["survey type"] == C.TYPE_RANDOM]
    latest = rand["submitted (local time)"].max()
    earliest = rand["submitted (local time)"].min()
    st.caption(
        f"Read {len(files)} file(s), {n_rows:,} rows"
        + (f" ({dups:,} duplicate response(s) removed)" if dups else "")
        + (f". Random surveys span {earliest:%Y-%m-%d} to {latest:%Y-%m-%d %H:%M} (participants' local time) "
           "-- counts are as of this date." if pd.notna(latest) else ".")
    )

    # --- who to look up ------------------------------------------------------
    pasted = st.text_area(
        "Subjects to look up (optional)",
        placeholder="Paste the IDs you're paying, separated by commas, spaces or new lines -- e.g. TEM0019, TEM0021, 34\n"
                    "Leave blank to see everyone.",
        height=90,
    )
    wanted = C.parse_id_list(pasted) or None
    summary = C.summarize(responses, int(threshold), wanted_subjects=wanted)

    view = st.radio("Show", ["Everyone", "Qualifying only", "Not yet qualifying"], horizontal=True)
    if view == "Qualifying only":
        summary = summary[summary["Qualifies"]]
    elif view == "Not yet qualifying":
        summary = summary[~summary["Qualifies"]]

    # --- headline numbers ------------------------------------------------------
    found = summary[summary["In files?"] == "yes"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Subjects shown", len(summary))
    m2.metric("Completed random surveys", int(found["Completed random surveys"].sum()))
    m3.metric(f"Reached {int(threshold)}", int(summary["Qualifies"].sum()))
    m4.metric("Partial surveys not counted", int(found["Partial (not counted)"].sum()))
    if wanted:
        missing = summary[summary["In files?"] != "yes"]["Subject"].tolist()
        if missing:
            st.warning(
                f"No data found in the uploaded files for: {', '.join(missing)}. Their rows show 0 -- that means "
                "'not in these files', not necessarily 'did no surveys'. Check you uploaded their export."
            )

    # --- the table ---------------------------------------------------------------
    display = summary.copy()
    display["Bonus status"] = display.apply(status_text, axis=1)
    cols = ["Subject", "Completed random surveys", "Bonus status", "Partial (not counted)", "Empty (not counted)",
            "Other surveys (not counted)", "All responses", "First survey", "Last survey"]
    if wanted:
        cols.append("In files?")
    st.dataframe(
        display[cols],
        hide_index=True,
        width="stretch",
        column_config={
            "Completed random surveys": st.column_config.ProgressColumn(
                f"Completed (of {int(threshold)})", min_value=0, max_value=int(threshold), format="%d",
                help="Complete random surveys only -- this is the number that counts toward the bonus.",
            ),
            "Partial (not counted)": st.column_config.NumberColumn(help="Started but exited early (items marked SKIPPED)."),
            "Other surveys (not counted)": st.column_config.NumberColumn(help="Urge assessments, the welcome survey, etc."),
            "All responses": st.column_config.NumberColumn(help="Every response of any kind -- roughly what MetricWire's own total shows."),
        },
    )

    # --- downloads -----------------------------------------------------------------
    subjects_in_view = set(summary["Subject"])
    resp_in_view = responses[responses["subject"].isin(subjects_in_view)]
    notes = [
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Bonus threshold", f"{int(threshold)} completed random surveys"),
        ("Files", ", ".join(f.name for f in files)),
        ("Random surveys span", f"{earliest:%Y-%m-%d} to {latest:%Y-%m-%d}" if pd.notna(latest) else "n/a"),
    ] + [("Rule", line) for line in RULES_TEXT]
    d1, d2, _ = st.columns([1, 1, 3])
    d1.download_button(
        "Download Excel (summary + every response)",
        C.build_excel(summary, resp_in_view, notes),
        file_name=f"ema_survey_counts_{datetime.now():%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    d2.download_button(
        "Download summary (CSV)",
        summary.to_csv(index=False),
        file_name=f"ema_survey_counts_{datetime.now():%Y-%m-%d}.csv",
        mime="text/csv",
    )

    # --- one subject in detail --------------------------------------------------------
    st.subheader("Look at one participant's responses")
    st.caption("Useful for explaining a count: every response, whether it counted, and if not, why.")
    options = found["Subject"].tolist()
    if not options:
        return
    who = st.selectbox("Participant", options)
    mine = responses[responses["subject"] == who]
    only_uncounted = st.checkbox("Only show responses that don't count", value=False)
    if only_uncounted:
        mine = mine[~mine["counts toward bonus"]]
    st.dataframe(
        mine[["submitted (local time)", "survey type", "status", "counts toward bonus", "why not counted",
              "items SKIPPED", "skipped items", "response ID"]],
        hide_index=True,
        width="stretch",
        column_config={"submitted (local time)": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")},
    )


if __name__ == "__main__":
    main()
