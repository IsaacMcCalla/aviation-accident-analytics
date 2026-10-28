"""Aviation accident dashboard as a web page (Streamlit).

Reads data/accidents.db, written by src/export_web_data.py. Runs in Docker (see web/README.md);
for a quick local run: streamlit run web/app.py
Counting rules match the Power BI model: accidents = distinct ev_id, so a midair counts once;
fatalities come from one row per event (is_primary_aircraft) so they are not double counted.
"""
import os
import sqlite3
from contextlib import closing

import altair as alt
import pandas as pd
import streamlit as st

DB = os.environ.get("ACCIDENT_DB", os.path.join(os.path.dirname(__file__), "data", "accidents.db"))
COLOR = "#0f9d8a"
FATAL_COLOR = "#33415c"

st.set_page_config(page_title="Aviation Accidents", page_icon="✈️", layout="wide")


@st.cache_data
def load(mtime: float) -> dict:
    """Load every table; mtime is part of the cache key, so a new export is picked up on the next page load."""
    with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {name: pd.read_sql(f"SELECT * FROM {name}", conn) for name in names}


def accident_stats(df: pd.DataFrame) -> dict:
    accidents = df["ev_id"].nunique()
    fatal = df.loc[df["is_fatal"] == 1, "ev_id"].nunique()
    deaths = int(df.loc[df["is_primary_aircraft"] == 1, "event_fatalities"].fillna(0).sum())
    return {"accidents": accidents, "fatal": fatal, "deaths": deaths, "pct": fatal / accidents if accidents else 0}


def by(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Accidents, fatal accidents and fatal share per value of one column."""
    g = df.groupby(column, dropna=False).agg(
        accidents=("ev_id", "nunique"),
        fatal=("ev_id", lambda s: s[df.loc[s.index, "is_fatal"] == 1].nunique()),
    ).reset_index()
    g["fatal_share"] = g["fatal"] / g["accidents"]
    return g


def bar(data: pd.DataFrame, category: str, value: str, title: str, sort=None, fmt=",.0f", horizontal=True):
    """Bar chart sorted largest first by default; pass sort=[...] for a fixed category order."""
    sort = sort or ("-x" if horizontal else "-y")
    axis = alt.Axis(format=".0%") if fmt.endswith("%") else alt.Axis(format="~s")
    if horizontal:
        enc = {"y": alt.Y(f"{category}:N", sort=sort, title=None), "x": alt.X(f"{value}:Q", title=None, axis=axis)}
    else:
        enc = {"x": alt.X(f"{category}:N", sort=sort, title=None, axis=alt.Axis(labelAngle=0)),
               "y": alt.Y(f"{value}:Q", title=None, axis=axis)}
    chart = alt.Chart(data, title=title).mark_bar(color=COLOR).encode(
        **enc, tooltip=[alt.Tooltip(f"{category}:N"), alt.Tooltip(f"{value}:Q", format=fmt)])
    st.altair_chart(chart, width="stretch")


if not os.path.exists(DB):
    st.error(f"No data file at {DB}. Run src/export_web_data.py first.")
    st.stop()

data = load(os.path.getmtime(DB))
acc, meta = data["accidents"], data["meta"].iloc[0]

# ---------------------------------------------------------------- sidebar filters
st.sidebar.title("Filters")
years = (int(acc["year"].min()), int(acc["year"].max()))
year_range = st.sidebar.slider("Years", *years, value=years)
us_only = st.sidebar.toggle("U.S. accidents only", value=False)
operations = st.sidebar.multiselect("Type of operation", sorted(acc["operation_name"].dropna().unique()))
st.sidebar.caption(f"Data exported {meta['exported_at'][:16].replace('T', ' ')}; "
                   f"latest event {meta['latest_event']}. Source: NTSB, FAA, OurAirports.")

f = acc[acc["year"].between(*year_range)]
if us_only:
    f = f[f["is_us"] == 1]
if operations:
    f = f[f["operation_name"].isin(operations)]
keys = set(f["accident_key"])

st.title("Aviation Accidents")
st.caption("NTSB accident data, 2008 to present. One accident can involve more than one aircraft; "
           "counts here are accidents (a midair collision counts once).")

tabs = st.tabs(["Overview", "Phase of flight", "Causes", "Aircraft", "Weather and pilot", "Map", "Accident list"])

# ---------------------------------------------------------------- overview
with tabs[0]:
    s = accident_stats(f)
    c = st.columns(4)
    c[0].metric("Accidents", f"{s['accidents']:,}")
    c[1].metric("Fatal accidents", f"{s['fatal']:,}")
    c[2].metric("Fatalities", f"{s['deaths']:,}")
    c[3].metric("Fatal share", f"{s['pct']:.1%}")

    left, right = st.columns([3, 2])
    with left:
        yearly = by(f, "year").melt(id_vars="year", value_vars=["accidents", "fatal"], var_name="series", value_name="count")
        yearly["series"] = yearly["series"].map({"accidents": "Accidents", "fatal": "Fatal accidents"})
        line = alt.Chart(yearly, title="Accidents by year (latest year is partial)").mark_line(point=True).encode(
            x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("count:Q", title=None),
            color=alt.Color("series:N", title=None, scale=alt.Scale(range=[COLOR, FATAL_COLOR]),
                            legend=alt.Legend(orient="top")),
            tooltip=["year:O", "series:N", alt.Tooltip("count:Q", format=",")])
        st.altair_chart(line, width="stretch")
    with right:
        bar(by(f, "operation_name"), "operation_name", "accidents", "Accidents by type of operation")

# ---------------------------------------------------------------- phase of flight
with tabs[1]:
    phases = by(f, "phase_group").merge(acc[["phase_group", "phase_group_order"]].drop_duplicates(), on="phase_group")
    order = phases.sort_values("phase_group_order")["phase_group"].tolist()
    left, right = st.columns(2)
    with left:
        bar(phases, "phase_group", "accidents", "Accidents by phase of flight", sort=order)
    with right:
        bar(phases, "phase_group", "fatal_share", "Fatal share by phase of flight", sort=order, fmt=".1%")
    detail = by(f, "phase_name").sort_values("accidents", ascending=False)
    st.dataframe(detail.rename(columns={"phase_name": "Detailed phase", "accidents": "Accidents",
                                        "fatal": "Fatal accidents", "fatal_share": "Fatal share"}),
                 column_config={"Fatal share": st.column_config.NumberColumn(format="percent")},
                 hide_index=True, width="stretch")

# ---------------------------------------------------------------- causes
with tabs[2]:
    tags = data["tags"][data["tags"]["accident_key"].isin(keys)]
    tag_stats = tags.groupby("tag").agg(accidents=("ev_id", "nunique")).reset_index()
    tag_stats["fatal_share"] = tags[tags["is_fatal"] == 1].groupby("tag")["ev_id"].nunique().reindex(
        tag_stats["tag"]).fillna(0).values / tag_stats["accidents"]
    left, right = st.columns(2)
    with left:
        bar(tag_stats, "tag", "accidents", "Accidents by narrative tag (keyword rules; undercounts)")
    with right:
        bar(tag_stats, "tag", "fatal_share", "Fatal share by narrative tag", fmt=".1%")
    findings = data["findings"][data["findings"]["accident_key"].isin(keys)]
    bar(findings.groupby("finding_category")["ev_id"].nunique().rename("accidents").reset_index(),
        "finding_category", "accidents", "Accidents by NTSB finding category")

# ---------------------------------------------------------------- aircraft
with tabs[3]:
    left, right = st.columns([3, 2])
    with left:
        makes = f.groupby("make")["ev_id"].nunique().rename("Accidents").reset_index()
        makes = makes.merge(data["fleet"], on="make", how="left").rename(
            columns={"make": "Make", "registered_aircraft": "Registered aircraft"})
        makes["Per 1,000 registered"] = (1000 * makes["Accidents"] / makes["Registered aircraft"]).where(
            makes["Registered aircraft"] >= 100)
        st.markdown("**Accidents vs. today's registered fleet** (exact make-name match; rate shown for 100+ registered)")
        st.dataframe(makes.sort_values("Accidents", ascending=False), hide_index=True, width="stretch", height=520,
                     column_config={"Per 1,000 registered": st.column_config.NumberColumn(format="%.1f")})
    with right:
        bar(by(f, "acft_category"), "acft_category", "accidents", "Accidents by aircraft category")

# ---------------------------------------------------------------- weather and pilot
with tabs[4]:
    left, right = st.columns(2)
    with left:
        bar(by(f, "weather"), "weather", "fatal_share", "Fatal share by weather conditions", fmt=".1%", horizontal=False)
    with right:
        bar(by(f, "light_cond"), "light_cond", "fatal_share", "Fatal share by light conditions", fmt=".1%", horizontal=False)
    hours = by(f, "pilot_hours_band").merge(acc[["pilot_hours_band", "pilot_hours_order"]].drop_duplicates(),
                                             on="pilot_hours_band")
    hours_order = hours.sort_values("pilot_hours_order")["pilot_hours_band"].tolist()
    left, right = st.columns(2)
    with left:
        bar(hours, "pilot_hours_band", "accidents", "Accidents by pilot total flight hours", sort=hours_order,
            horizontal=False)
    with right:
        bar(hours, "pilot_hours_band", "fatal_share", "Fatal share by pilot total flight hours", sort=hours_order,
            fmt=".1%", horizontal=False)

# ---------------------------------------------------------------- map
with tabs[5]:
    fatal_only = st.toggle("Fatal accidents only", value=False)
    events = f[f["is_fatal"] == 1] if fatal_only else f
    events = events.drop_duplicates("ev_id")
    located = events.dropna(subset=["latitude", "longitude"])
    missing = 1 - len(located) / len(events) if len(events) else 0
    st.caption(f"{len(located):,} accidents with coordinates; {missing:.0%} have none in the source "
               "(mostly outside the U.S.). Map tiles load from the internet.")
    st.map(located, latitude="latitude", longitude="longitude", size=800, color=COLOR + "aa")

# ---------------------------------------------------------------- accident list
with tabs[6]:
    query = st.text_input("Search make, model, city, state or probable cause")
    rows = f
    if query:
        text = (f["make"].fillna("") + " " + f["model"].fillna("") + " " + f["ev_city"].fillna("") + " " +
                f["ev_state"].fillna("") + " " + f["probable_cause"].fillna(""))
        rows = f[text.str.contains(query, case=False, regex=False)]
    st.caption(f"{len(rows):,} aircraft rows")
    st.dataframe(
        rows.sort_values("ev_date", ascending=False)[
            ["ev_date", "ntsb_no", "ev_state", "ev_city", "make", "model", "phase_name", "highest_injury",
             "event_fatalities", "probable_cause"]].rename(columns={
                "ev_date": "Date", "ntsb_no": "NTSB no.", "ev_state": "State", "ev_city": "City", "make": "Make",
                "model": "Model", "phase_name": "Phase", "highest_injury": "Highest injury",
                "event_fatalities": "Fatalities", "probable_cause": "Probable cause"}),
        hide_index=True, width="stretch", height=600)
