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
FATAL_COLOR = "#e07a5f"   # readable on both the light and dark themes
WEATHER = {"VMC": "Visual (VMC)", "IMC": "Instrument (IMC)", "UNK": "Unknown"}
FLIGHT_CATEGORIES = ["VFR", "MVFR", "IFR", "LIFR"]   # best to worst

st.set_page_config(page_title="Aviation Accidents", page_icon="✈️", layout="wide")


@st.cache_data
def load(mtime: float) -> dict:
    """Load every table; mtime is part of the cache key, so a new export is picked up on the next page load."""
    with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        data = {name: pd.read_sql(f"SELECT * FROM {name}", conn) for name in names}
    # The export stores codes and keys only, to keep the file small; restore names and ev_id here
    acc = data["accidents"]
    acc["weather"] = acc["weather"].map(WEATHER).fillna("Unknown")
    ev_ids = acc[["accident_key", "ev_id"]]
    data["tags"] = data["tags"].merge(ev_ids, on="accident_key")
    data["findings"] = data["findings"].merge(data["finding_categories"], on="category_id").merge(ev_ids, on="accident_key")
    return data


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


def phrase(name: str) -> str:
    """Lower-case a label for use mid-sentence, unless it contains an acronym (VFR, IMC)."""
    return name if any(len(w) > 1 and w.isupper() for w in name.split()) else name.lower()


def bar(data: pd.DataFrame, category: str, value: str, title: str, sort=None, fmt=",.0f", horizontal=True):
    """Bar chart sorted largest first by default; pass sort=[...] for a fixed category order."""
    sort = sort or ("-x" if horizontal else "-y")
    axis = alt.Axis(format=".0%") if fmt.endswith("%") else alt.Axis(format="~s")
    if horizontal:
        enc = {"y": alt.Y(f"{category}:N", sort=sort, title=None, axis=alt.Axis(labelLimit=260)),
               "x": alt.X(f"{value}:Q", title=None, axis=axis)}
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
st.caption("NTSB accident data, 1982 to present. One accident can involve more than one aircraft; "
           "counts here are accidents (a midair collision counts once).")

tabs = st.tabs(["Findings", "Overview", "Phase of flight", "Causes", "Aircraft", "Weather and pilot", "Map",
                "Accident list"])

# ---------------------------------------------------------------- findings
with tabs[0]:
    ga = acc[(acc["is_ga"] == 1) & (acc["is_primary_aircraft"] == 1)]
    st.markdown(f"**Key findings for U.S. general aviation** ({ga['ev_id'].nunique():,} accidents, "
                f"{int(ga['year'].min())} to {meta['latest_event'][:4]}). These use every year and ignore the sidebar "
                "filters. General aviation is civil flying other than airlines and charter (Parts 121 and 135).")

    # 1. Rates: the NTSB's published counts over FAA flight-hour estimates
    # keep years without flight hours as empty values, so the line shows a gap instead of bridging it
    rates = data["rates"][data["rates"]["year"].between(1982, data["rates"].dropna(subset=["ga_hours"])["year"].max())]
    rated = rates.dropna(subset=["ga_hours"])
    early = rated[rated["year"].between(1990, 1994)]["ntsb_fatal_per_100k_hours"].mean()
    last = int(rated["year"].max())
    late = rated[rated["year"].between(last - 4, last)]["ntsb_fatal_per_100k_hours"].mean()
    st.subheader(f"1. Flying got safer: the fatal accident rate fell {1 - late / early:.0%}")
    st.write(f"The NTSB's general aviation fatal accident rate averaged {early:.2f} per 100,000 flight hours in "
             f"1990-1994 and {late:.2f} in {last - 4}-{last}. Flight hours "
             "changed far less than accidents did, so this is not just less flying.")
    long = rates.melt(id_vars="year", value_vars=["ntsb_fatal_per_100k_hours", "fatal_per_100k_hours"],
                      var_name="series", value_name="rate")
    long["series"] = long["series"].map({"ntsb_fatal_per_100k_hours": "NTSB published",
                                         "fatal_per_100k_hours": "This project's count"})
    st.altair_chart(alt.Chart(long, title="Fatal accidents per 100,000 flight hours").mark_line(point=True).encode(
        x=alt.X("year:Q", title=None, axis=alt.Axis(format="d")), y=alt.Y("rate:Q", title=None),
        color=alt.Color("series:N", title=None, scale=alt.Scale(range=[FATAL_COLOR, COLOR]), legend=alt.Legend(orient="top")),
        tooltip=["year:Q", "series:N", alt.Tooltip("rate:Q", format=".2f")]), width="stretch")
    st.caption("Flight hours: FAA estimates via BTS Table 2-14 (none for 1982-84, 1986-89 and 2011). This project's "
               "counts are within about 3% of the NTSB's published accident counts.")

    decades = by(ga.assign(decade=ga["year"] // 10 * 10), "decade")
    st.subheader("2. Fewer accidents, not milder ones")
    st.write(f"The share of accidents that were fatal barely moved: {decades['fatal_share'].iloc[0]:.1%} in the "
             f"{int(decades['decade'].iloc[0])}s and {decades['fatal_share'].iloc[-1]:.1%} in the "
             f"{int(decades['decade'].iloc[-1])}s. The gains came from preventing accidents, not from surviving them.")

    wx = by(ga, "weather").set_index("weather")["fatal_share"]
    st.subheader(f"3. Instrument weather makes an accident {wx['Instrument (IMC)'] / wx['Visual (VMC)']:.1f}x as likely to be fatal")
    left, right = st.columns([2, 3])
    with left:
        st.write(f"{wx['Instrument (IMC)']:.0%} of accidents in instrument conditions (clouds, low visibility) were "
                 f"fatal, against {wx['Visual (VMC)']:.0%} in visual conditions. The weather call is the NTSB "
                 "investigator's.")
    with right:
        bar(by(ga, "weather"), "weather", "fatal_share", "Fatal share by weather", fmt=".1%")

    phases = by(ga, "phase_group")
    phases["All accidents"] = phases["accidents"] / phases["accidents"].sum()
    phases["Fatal accidents"] = phases["fatal"] / phases["fatal"].sum()
    man = phases.set_index("phase_group").loc["Maneuvering"]
    land = phases.set_index("phase_group").loc["Landing"]
    st.subheader("4. Maneuvering is deadly; landing is not")
    left, right = st.columns([2, 3])
    with left:
        st.write(f"Maneuvering (low passes, turns, aerobatics) is {man['All accidents']:.0%} of accidents but "
                 f"{man['Fatal accidents']:.0%} of fatal ones. Landing is {land['All accidents']:.0%} "
                 f"of accidents but {land['Fatal accidents']:.0%} of fatal ones.")
    with right:
        top = phases[phases["accidents"] >= 1000].melt(id_vars="phase_group",
                                                       value_vars=["All accidents", "Fatal accidents"])
        st.altair_chart(alt.Chart(top, title="Share of accidents by phase of flight").mark_bar().encode(
            y=alt.Y("phase_group:N", title=None, sort="-x"), x=alt.X("value:Q", title=None, axis=alt.Axis(format=".0%")),
            yOffset="variable:N", color=alt.Color("variable:N", title=None, legend=alt.Legend(orient="top"),
                                                  scale=alt.Scale(range=[COLOR, FATAL_COLOR])),
            tooltip=["phase_group:N", "variable:N", alt.Tooltip("value:Q", format=".1%")]), width="stretch")

    tags = data["tags"][data["tags"]["accident_key"].isin(set(ga["accident_key"]))]
    tag_stats = tags.groupby("tag").agg(accidents=("ev_id", "nunique"), fatal=("is_fatal", "sum")).reset_index()
    tag_stats["fatal_share"] = tag_stats["fatal"] / tag_stats["accidents"]
    tag_stats = tag_stats[tag_stats["accidents"] >= 150]
    common = tag_stats.nlargest(2, "accidents")
    deadly = tag_stats.nlargest(3, "fatal_share")
    st.subheader("5. The most common problems are the most survivable")
    st.write(f"The two most common accident types in the narratives, {phrase(common['tag'].iloc[0])} and "
             f"{phrase(common['tag'].iloc[1])}, were fatal {common['fatal_share'].min():.0%}-"
             f"{common['fatal_share'].max():.0%} of the time. The deadliest types almost always were: "
             + ", ".join(f"{phrase(t)} ({s:.0%})" for t, s in zip(deadly["tag"], deadly["fatal_share"])) + ".")
    bar(tag_stats, "tag", "fatal_share", "Fatal share by accident type (narrative keyword tags; 150+ accidents)", fmt=".0%")

    run = data["model_run"].iloc[0]
    factors = data["model_factors"]
    factors = factors[(factors["accidents"] >= 200) & ~factors["level"].isin(["Unknown", "Other/unknown", "Other"])]
    factors = pd.concat([factors.nlargest(8, "odds_ratio"), factors.nsmallest(4, "odds_ratio")])
    is_tag = factors["factor_name"].str.startswith("Narrative: ")
    factors["label"] = (factors["factor_name"].str.removeprefix("Narrative: ").str.capitalize() + " (narrative)").where(
        is_tag, factors["level"] + " (vs. " + factors["reference_level"] + ")")
    st.subheader("6. A simple model confirms it")
    st.write(f"A logistic regression trained on 1982-2018 ranks a fatal accident above a non-fatal one "
             f"{run['lr_roc_auc']:.0%} of the time on {run['test_rows']:,.0f} accidents from 2019 on that it never saw "
             f"(a flexible gradient-boosting model reaches {run['gb_roc_auc']:.0%}). Phase of flight carries most of "
             "that. Odds ratios hold the other factors equal; above 1 means higher odds of a fatal outcome.")
    factors["direction"] = factors["odds_ratio"].map(lambda r: "Higher odds" if r > 1 else "Lower odds")
    # bars grow from 1.0 ("no difference"): a log axis has no zero to start from
    st.altair_chart(alt.Chart(factors, title="Odds of a fatal outcome, other factors equal (log scale)").mark_bar().encode(
        y=alt.Y("label:N", title=None, sort="-x", axis=alt.Axis(labelLimit=340)),
        x=alt.X("odds_ratio:Q", title=None, scale=alt.Scale(type="log")), x2=alt.datum(1),
        color=alt.Color("direction:N", title=None, legend=None,
                        scale=alt.Scale(domain=["Higher odds", "Lower odds"], range=[FATAL_COLOR, COLOR])),
        tooltip=[alt.Tooltip("factor_name:N", title="Factor"), alt.Tooltip("label:N", title="Level"),
                 alt.Tooltip("odds_ratio:Q", format=".2f"), alt.Tooltip("accidents:Q", format=","),
                 alt.Tooltip("fatal_share:Q", format=".1%")]), width="stretch")
    st.caption("Associations in accident records, not causes. Narrative tags are keyword rules that undercount, "
               "and pre-2008 narratives are terser. Full method: docs/model_report.md and docs/findings.md in the "
               "GitHub repository.")

# ---------------------------------------------------------------- overview
with tabs[1]:
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
with tabs[2]:
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
with tabs[3]:
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
    st.caption("The NTSB changed its cause coding in 2008. Earlier accidents use the older system, shown as "
               "\"Pre-2008:\" categories rather than forced into the newer ones.")

# ---------------------------------------------------------------- aircraft
with tabs[4]:
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
with tabs[5]:
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

    # Observed weather: the nearest station's report at the time (U.S. accidents only)
    if "observed_category" in f.columns:
        observed = f[f["observed_category"].notna()]
        matched = acc[acc["observed_category"].notna()]["year"]
        # station matching may not cover every year yet (enrich_weather.py runs incrementally)
        y0, y1 = (int(matched.min()), int(matched.max())) if len(matched) else (0, 0)
        us = f[(f["is_us"] == 1) & f["year"].between(y0, y1)]["ev_id"].nunique()
        st.markdown(f"**Observed weather at the nearest station** (within 40 km and 90 minutes of the accident). "
                    f"Station reports have been matched for accidents from **{y0} to {y1}** so far.")
        if len(observed):
            cats = by(observed, "observed_category")
            left, right = st.columns(2)
            with left:
                bar(cats, "observed_category", "fatal_share", "Fatal share by observed category", fmt=".1%",
                    sort=FLIGHT_CATEGORIES, horizontal=False)
            with right:
                bar(cats, "observed_category", "accidents", "Accidents by observed category",
                    sort=FLIGHT_CATEGORIES, horizontal=False)
            st.caption(f"{observed['ev_id'].nunique():,} of {us:,} U.S. accidents in the selection from {y0} to {y1} "
                       "matched a station report. VFR: ceiling above 3,000 ft and visibility over 5 miles; MVFR: marginal; IFR: ceiling "
                       "under 1,000 ft or visibility under 3 miles; LIFR: under 500 ft or 1 mile. The station can be "
                       "up to 40 km away, so conditions at the site may differ.")
        else:
            st.caption("No accidents in the selection matched a station report.")

# ---------------------------------------------------------------- map
with tabs[6]:
    fatal_only = st.toggle("Fatal accidents only", value=False)
    events = f[f["is_fatal"] == 1] if fatal_only else f
    events = events.drop_duplicates("ev_id")
    located = events.dropna(subset=["latitude", "longitude"])
    missing = 1 - len(located) / len(events) if len(events) else 0
    st.caption(f"{len(located):,} accidents with coordinates; {missing:.0%} have none in the source "
               "(mostly outside the U.S.). Map tiles load from the internet.")
    st.map(located, latitude="latitude", longitude="longitude", size=800, color=COLOR + "aa")

# ---------------------------------------------------------------- accident list
with tabs[7]:
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
