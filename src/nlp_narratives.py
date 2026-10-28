"""Tag accident narratives with keyword rules and write the tags to dbo.fact_narrative_tag.

    python src/nlp_narratives.py                  # rebuild all tags
    python src/nlp_narratives.py --top-terms 40   # also print the top TF-IDF terms (needs scikit-learn)

Run after sql/02_transform.sql. The rules are deliberately simple and readable. Cause rules
search only the probable-cause statement: factual narratives quote FAA guidance and
toxicology results ("negative for drugs and alcohol") that would give false matches.
Event rules (things that physically happened) also search the factual narrative.
Use --top-terms to find phrases worth adding as new rules, and spot-check a sample of
tagged events before quoting any numbers.
"""
import argparse
import re

from config import get_connection, insert_sql, log_run, setup_logging

log = setup_logging("nlp_narratives")

# tag -> (pattern, where to search: "cause" = probable cause only, "all" = cause + factual narrative)
TAGS = {
    "fuel_exhaustion": (r"\bfuel (exhaustion|starvation)\b", "cause"),
    "loss_of_control": (r"\bloss of (aircraft )?control\b", "cause"),
    "vfr_into_imc": (r"\b(vfr|visual flight rules( \(vfr\))?) (flight )?in(to)? (imc|instrument meteorological conditions)\b"
                     r"|\bvfr encounter with imc\b"
                     r"|\binadvertent(ly)? (encounter(ed)? with|entry into|entered|flew into) (imc|instrument meteorological conditions)\b"
                     r"|\bflight into (imc|instrument meteorological conditions)\b", "cause"),
    "stall": (r"\b(aerodynamic stall|exceed(ed|ance of) the [a-z]+'s critical angle of attack|stall/spin)\b", "cause"),
    "cfit": (r"\b(controlled flight into terrain|failure to maintain (adequate )?(terrain|obstacle) clearance)\b", "cause"),
    "maintenance": (r"\b(improper|inadequate) maintenance\b", "cause"),
    "density_altitude": (r"\bhigh density altitude\b", "cause"),
    "spatial_disorientation": (r"\bspatial disorientation\b", "cause"),
    "impairment": (r"\bimpair(ment|ed)\b|\b(use|effects) of (alcohol|ethanol|marijuana|impairing)\b", "cause"),
    "crosswind": (r"\bcrosswind\b", "cause"),
    "engine_power_loss": (r"\b((total|partial) loss of engine power|engine failure)\b", "all"),
    "midair": (r"\bmid-?air collision\b", "all"),
    "wire_strike": (r"\b(collided with|struck) (power ?lines|wires|utility lines)\b", "all"),
    "bird_strike": (r"\b(bird ?strike|collision with (a )?birds?)\b", "all"),
}
PATTERNS = {tag: (re.compile(rx, re.IGNORECASE), scope) for tag, (rx, scope) in TAGS.items()}


def print_top_terms(texts: list, n: int) -> None:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        log.warning("--top-terms needs scikit-learn: pip install scikit-learn")
        return
    vec = TfidfVectorizer(ngram_range=(2, 3), stop_words="english", min_df=20, max_features=20_000)
    matrix = vec.fit_transform(texts)
    scores = matrix.mean(axis=0).A1
    terms = vec.get_feature_names_out()
    for score, term in sorted(zip(scores, terms), reverse=True)[:n]:
        print(f"{score:.4f}  {term}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-terms", type=int, default=0)
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    try:
        narratives = cur.execute(
            "SELECT ev_id, aircraft_key_ntsb, ISNULL(narr_cause, N''), ISNULL(narr_accp, N'') FROM dbo.fact_narrative"
        ).fetchall()
        rows = []
        for ev_id, aircraft_key, cause, factual in narratives:
            texts = {"cause": cause, "all": f"{cause}\n{factual}"}
            rows.extend((ev_id, aircraft_key, tag) for tag, (rx, scope) in PATTERNS.items() if rx.search(texts[scope]))

        cur.fast_executemany = True
        cur.execute("TRUNCATE TABLE dbo.fact_narrative_tag")
        if rows:
            cur.executemany(insert_sql("fact_narrative_tag", ["ev_id", "aircraft_key_ntsb", "tag"]), rows)
        conn.commit()
        log.info("tagged %d narratives: %d tags", len(narratives), len(rows))
        log_run(conn, "nlp_tags", "OK", len(rows), f"{len(narratives)} narratives, {len(TAGS)} rules")

        if args.top_terms:
            print_top_terms([cause for _, _, cause, _ in narratives if cause], args.top_terms)
    except Exception as exc:
        log.exception("narrative tagging failed")
        log_run(conn, "nlp_tags", "FAILED", 0, str(exc))
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
