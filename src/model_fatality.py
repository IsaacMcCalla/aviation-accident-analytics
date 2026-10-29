"""Which circumstances of a U.S. general aviation accident go with it being fatal?

    python src/model_fatality.py

Fits two models on U.S. general aviation accidents (dbo.vw_ga_accident, one row per event):
  - logistic regression: each factor gets an odds ratio, readable without a statistics background;
  - gradient boosting: a flexible benchmark, to show how much the simple model leaves on the table.
Trains on 1982-2018 and tests on 2019 onward, so the scores show how the model does on years it
never saw. Inputs describe the flight and the conditions, never the outcome: damage, injuries and
NTSB findings are left out on purpose (they would give the answer away).

Writes dbo.model_fatality_factor (odds ratio per factor level) and dbo.model_run (scores), and a
readable summary to docs/model_report.md. Run after enrich_weather.py and nlp_narratives.py.
These are associations in accident data, not causes, and say nothing about how likely a
flight is to have an accident in the first place.
"""
import datetime
import os

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from config import get_connection, insert_sql, log_run, setup_logging

log = setup_logging("model_fatality")

REPORT = os.path.join("docs", "model_report.md")
TEST_FROM = 2019
SEED = 42
# Observed station weather (dbo.fact_event_weather) is off while enrich_weather.py is on hold:
# a partial run covers only some years, which would make the weather inputs stand in for the era.
# Turn it on once that table covers every year.
USE_STATION_WEATHER = False
STATION_FACTORS = ["observed_category", "ceiling", "wind"]

DATA_SQL = """
SELECT g.ev_id, YEAR(g.ev_date) AS [year], CAST(g.is_fatal AS int) AS is_fatal,
       p.phase_group, wc.wx_code AS ntsb_weather, ISNULL(g.light_cond, 'UNK') AS light_cond,
       da.acft_category, da.num_eng, g.homebuilt, o.far_part, g.pilot_hours_band, g.pilot_age,
       w.flight_category, w.ceiling_ft, w.wind_kt, w.gust_kt, w.station_choice
FROM dbo.vw_ga_accident g
JOIN dbo.dim_phase p          ON p.phase_key = g.phase_key
JOIN dbo.dim_weather_cond wc  ON wc.wx_cond_key = g.wx_cond_key
JOIN dbo.dim_aircraft da      ON da.aircraft_dim_key = g.aircraft_dim_key
JOIN dbo.dim_operation o      ON o.operation_key = g.operation_key
LEFT JOIN dbo.fact_event_weather w ON w.ev_id = g.ev_id
WHERE g.is_primary_aircraft = 1
"""
TAGS_SQL = "SELECT DISTINCT ev_id, tag FROM dbo.fact_narrative_tag"

# Readable names for the factors in the report and dashboards
FACTOR_NAMES = {
    "phase_group": "Phase of flight", "ntsb_weather": "Weather (NTSB)", "light_cond": "Light",
    "aircraft": "Aircraft category", "engines": "Engines", "homebuilt": "Amateur-built",
    "operation": "Type of operation", "pilot_hours_band": "Pilot total hours", "pilot_age": "Pilot age",
    "observed_category": "Observed flight category", "ceiling": "Observed ceiling", "wind": "Observed wind",
    "decade": "Decade",
}
LIGHT = {"DAYL": "Day", "NITE": "Night (unspecified)", "NDRK": "Night, dark", "NBRT": "Night, bright",
         "DUSK": "Dusk", "DAWN": "Dawn", "UNK": "Unknown"}
CATEGORY = {"AIR": "Airplane", "HELI": "Helicopter", "GLI": "Glider", "BALL": "Balloon", "GYRO": "Gyroplane",
            "WSFT": "Weight-shift", "PPAR": "Powered parachute"}
# Reference level per factor: odds ratios are relative to these
REFERENCE = {"phase_group": "Takeoff", "ntsb_weather": "VMC", "light_cond": "Day", "aircraft": "Airplane",
             "engines": "1", "homebuilt": "No", "operation": "Personal and other Part 91",
             "pilot_hours_band": "1,000-4,999", "pilot_age": "40-59", "observed_category": "VFR",
             "ceiling": "No ceiling", "wind": "0-9 kt", "decade": "1990s"}


def band(value, edges, labels, missing="Unknown"):
    if value is None or pd.isna(value):
        return missing
    for edge, label in zip(edges, labels):
        if value < edge:
            return label
    return labels[-1]


def prepare(df: pd.DataFrame, tags: pd.DataFrame) -> pd.DataFrame:
    """Turn raw columns into the categorical factors the models use."""
    x = pd.DataFrame(index=df.index)
    x["phase_group"] = df["phase_group"]
    x["ntsb_weather"] = df["ntsb_weather"].replace({"UNK": "Unknown"})
    x["light_cond"] = df["light_cond"].map(LIGHT).fillna("Unknown")
    x["aircraft"] = df["acft_category"].map(CATEGORY).fillna("Other/unknown")
    x["engines"] = df["num_eng"].map(lambda n: "Unknown" if pd.isna(n) else ("2+" if n >= 2 else str(int(n))))
    x["homebuilt"] = df["homebuilt"].map({1: "Yes", 0: "No", True: "Yes", False: "No"}).fillna("Unknown")
    x["operation"] = np.where(df["far_part"] == "137", "Agricultural (Part 137)",
                     np.where(df["far_part"] == "PUBU", "Public aircraft",
                     np.where(df["far_part"].isin(["091", "091K", "091F", "103"]), "Personal and other Part 91",
                              "Other")))
    x["pilot_hours_band"] = df["pilot_hours_band"]
    x["pilot_age"] = df["pilot_age"].map(lambda a: band(a, [25, 40, 60, 70], ["Under 25", "25-39", "40-59", "60-69", "70+"]))
    matched = df["station_choice"].isin(["ntsb", "nearest"])
    x["observed_category"] = np.where(matched, df["flight_category"].fillna("Unknown"), "No station report")
    x["ceiling"] = np.where(~matched, "No station report",
                            df["ceiling_ft"].map(lambda c: band(c, [500, 1000, 3000], ["Under 500 ft", "500-999 ft",
                                                                                      "1,000-2,999 ft", "3,000 ft+"],
                                                                missing="No ceiling")))
    wind = df[["wind_kt", "gust_kt"]].max(axis=1)
    x["wind"] = np.where(~matched, "No station report",
                         wind.map(lambda w: band(w, [10, 20, 30], ["0-9 kt", "10-19 kt", "20-29 kt", "30 kt+"])))
    x["decade"] = (df["year"] // 10 * 10).astype(str) + "s"
    if not USE_STATION_WEATHER:
        x = x.drop(columns=STATION_FACTORS)

    # Accident type from the narrative tags: 1 if the narrative mentions it
    for tag in sorted(tags["tag"].unique()):
        ids = set(tags.loc[tags["tag"] == tag, "ev_id"])
        x[f"tag_{tag}"] = df["ev_id"].isin(ids).map({True: "Yes", False: "No"})
        REFERENCE.setdefault(f"tag_{tag}", "No")
        FACTOR_NAMES.setdefault(f"tag_{tag}", "Narrative: " + tag.replace("_", " "))
    return x


def make_encoder(x: pd.DataFrame) -> ColumnTransformer:
    cols = list(x.columns)
    drop = [REFERENCE[c] if REFERENCE.get(c) in set(x[c]) else x[c].mode()[0] for c in cols]
    return ColumnTransformer([("cat", OneHotEncoder(drop=drop, handle_unknown="ignore", min_frequency=30), cols)])


def scores(y, p) -> dict:
    return {"roc_auc": roc_auc_score(y, p), "pr_auc": average_precision_score(y, p), "brier": brier_score_loss(y, p)}


def factor_table(x: pd.DataFrame, y: pd.Series, lr: Pipeline) -> pd.DataFrame:
    enc = lr.named_steps["prep"]
    names = enc.get_feature_names_out()
    coefs = lr.named_steps["model"].coef_[0]
    rows = []
    for name, coef in zip(names, coefs):
        col, level = _split(name, x.columns)
        if level == "infrequent_sklearn":
            continue
        mask = x[col] == level
        rows.append({"factor": col, "factor_name": FACTOR_NAMES.get(col, col), "level": level,
                     "reference_level": REFERENCE.get(col), "odds_ratio": float(np.exp(coef)),
                     "accidents": int(mask.sum()), "fatal_share": float(y[mask].mean()) if mask.any() else None})
    return pd.DataFrame(rows).sort_values("odds_ratio", ascending=False)


def _split(feature_name: str, columns) -> tuple:
    """'cat__phase_group_Approach' -> ('phase_group', 'Approach'), matching the longest column name."""
    body = feature_name.split("__", 1)[1]
    col = max((c for c in columns if body.startswith(c + "_")), key=len)
    return col, body[len(col) + 1:]


def write_report(run: dict, factors: pd.DataFrame, perm: pd.DataFrame) -> None:
    def fmt_rows(df):
        return "\n".join(
            f"| {r.factor_name} | {r.level} (vs. {r.reference_level}) | {r.odds_ratio:.2f} | {r.accidents:,} | {r.fatal_share:.1%} |"
            for r in df.itertuples())
    # "Unknown" levels say how a record was coded, not something about the flight: keep them out of the highlights
    shown = factors[(factors["accidents"] >= 200) & ~factors["level"].isin(["Unknown", "Other/unknown", "Other"])]
    top = shown.head(12)
    bottom = shown.tail(6).iloc[::-1]
    text = f"""# Fatality model report

*Generated by `src/model_fatality.py` on {run['run_at']:%Y-%m-%d}. Re-run it after each data update; do not edit by hand.*

**Question:** among U.S. general aviation accidents, which circumstances go with the accident being fatal?
This is about how bad an accident is once it happens, not how likely a flight is to have one.

## Data and method

- {run['train_rows'] + run['test_rows']:,} U.S. general aviation accidents (one row per event, 1982 onward; the same set as `dbo.vw_ga_accident`).
- Trained on 1982-{TEST_FROM - 1} ({run['train_rows']:,} accidents), tested on {TEST_FROM} onward ({run['test_rows']:,}), so the scores show performance on years the model never saw.
- Inputs: phase of flight, weather (the NTSB's VMC/IMC call{' and the observed station report' if USE_STATION_WEATHER else ''}), light, aircraft category, engines, amateur-built, type of operation, pilot hours and age, decade, and narrative accident-type tags. Damage, injuries and NTSB findings are left out because they describe the outcome.
- Two models: logistic regression (gives each factor an odds ratio) and gradient boosting (a flexible benchmark).

## How well it predicts (test years)

| Model | ROC AUC | PR AUC | Brier score |
| --- | --- | --- | --- |
| Logistic regression | {run['lr_roc_auc']:.3f} | {run['lr_pr_auc']:.3f} | {run['lr_brier']:.3f} |
| Gradient boosting | {run['gb_roc_auc']:.3f} | {run['gb_pr_auc']:.3f} | {run['gb_brier']:.3f} |
| Baseline (always guess the average) | 0.500 | {run['test_fatal_share']:.3f} | {run['baseline_brier']:.3f} |

ROC AUC is the chance the model ranks a random fatal accident above a random non-fatal one (0.5 = guessing, 1.0 = perfect).
{run['test_fatal_share']:.1%} of test-year accidents were fatal. The simple model is {'within 0.02' if abs(run['gb_roc_auc'] - run['lr_roc_auc']) < 0.02 else 'behind the benchmark by ' + format(run['gb_roc_auc'] - run['lr_roc_auc'], '.3f')} of the flexible one, so its odds ratios are a fair summary.

## Factors that go with fatal outcomes

Odds ratio = how the odds of a fatal outcome compare with the reference level, **holding the other factors equal**. 2.0 means double the odds; 0.5 means half. Odds are not probabilities: when the reference level is rarely fatal, ratios get large, so read them next to the fatal share. Only levels with at least 200 accidents are shown, and "unknown" levels are left out; every level is in `dbo.model_fatality_factor`.

| Factor | Level | Odds ratio | Accidents | Fatal share |
| --- | --- | --- | --- | --- |
{fmt_rows(top)}

**Lowest odds of a fatal outcome:**

| Factor | Level | Odds ratio | Accidents | Fatal share |
| --- | --- | --- | --- | --- |
{fmt_rows(bottom)}

## Which inputs matter most (gradient boosting)

Drop in test ROC AUC when each input is shuffled (bigger = the model relies on it more):

| Input | AUC drop |
| --- | --- |
{chr(10).join(f"| {FACTOR_NAMES.get(r.factor, r.factor)} | {r.auc_drop:.3f} |" for r in perm.head(10).itertuples())}

## Read with care

- These are associations, not causes. Phase, weather and accident type are linked to each other and to things the data does not record (speed and angle at impact, terrain, survival equipment).
- Narrative tags come from the investigators' text and keyword rules that undercount; older narratives are terser.
{'- Observed weather is from the nearest station, up to 40 km away and 90 minutes from the accident; conditions at the site can differ.' if USE_STATION_WEATHER else '- Weather is the NTSB investigator' + chr(39) + 's VMC/IMC call only; observed station weather is on hold (see `enrich_weather.py`).'}
"""
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    conn = get_connection()
    try:
        df = pd.read_sql(DATA_SQL, conn)
        tags = pd.read_sql(TAGS_SQL, conn)
        x = prepare(df, tags)
        y = df["is_fatal"]
        train, test = df["year"] < TEST_FROM, df["year"] >= TEST_FROM
        log.info("%d accidents (%d train, %d test), fatal share %.1f%%", len(df), train.sum(), test.sum(), 100 * y.mean())

        lr = Pipeline([("prep", make_encoder(x)), ("model", LogisticRegression(C=1.0, max_iter=2000))])
        lr.fit(x[train], y[train])
        gb = Pipeline([("prep", ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=30,
                                                                          sparse_output=False), list(x.columns))])),
                       ("model", HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=SEED))])
        gb.fit(x[train], y[train])

        p_lr, p_gb = lr.predict_proba(x[test])[:, 1], gb.predict_proba(x[test])[:, 1]
        s_lr, s_gb = scores(y[test], p_lr), scores(y[test], p_gb)
        base = y[train].mean()
        run = {"run_at": datetime.datetime.now().replace(microsecond=0), "train_rows": int(train.sum()),
               "test_rows": int(test.sum()), "test_fatal_share": float(y[test].mean()),
               "baseline_brier": brier_score_loss(y[test], np.full(test.sum(), base)),
               **{f"lr_{k}": v for k, v in s_lr.items()}, **{f"gb_{k}": v for k, v in s_gb.items()}}
        log.info("test ROC AUC: logistic %.3f, boosting %.3f", s_lr["roc_auc"], s_gb["roc_auc"])

        # Permutation importance by input column (shuffle one input, measure the AUC drop)
        rng = np.random.default_rng(SEED)
        xt = x[test].copy()
        perm = []
        for col in x.columns:
            shuffled = xt.copy()
            shuffled[col] = rng.permutation(shuffled[col].values)
            perm.append({"factor": col, "auc_drop": s_gb["roc_auc"] - roc_auc_score(y[test], gb.predict_proba(shuffled)[:, 1])})
        perm = pd.DataFrame(perm).sort_values("auc_drop", ascending=False)

        factors = factor_table(x, y, lr)

        cur = conn.cursor()
        cur.execute("DELETE dbo.model_fatality_factor")
        cols = ["factor", "factor_name", "level", "reference_level", "odds_ratio", "accidents", "fatal_share"]
        cur.executemany(insert_sql("model_fatality_factor", cols),
                        [tuple(None if pd.isna(v) else v for v in r) for r in factors[cols].itertuples(index=False)])
        run_cols = ["run_at", "train_rows", "test_rows", "test_fatal_share", "baseline_brier",
                    "lr_roc_auc", "lr_pr_auc", "lr_brier", "gb_roc_auc", "gb_pr_auc", "gb_brier"]
        cur.execute(insert_sql("model_run", run_cols), *[run[c] for c in run_cols])
        conn.commit()

        write_report(run, factors, perm)
        log.info("wrote %d factor levels and %s", len(factors), REPORT)
        log_run(conn, "model", "OK", len(df), f"test AUC lr={s_lr['roc_auc']:.3f} gb={s_gb['roc_auc']:.3f}")
    except Exception as exc:
        log.exception("model run failed")
        log_run(conn, "model", "FAILED", 0, str(exc)[:500])
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
