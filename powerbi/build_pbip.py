"""Generate the Power BI project (PBIP) for the accident dashboard.

    .venv\\Scripts\\python.exe powerbi\\build_pbip.py            # opens on the first page
    .venv\\Scripts\\python.exe powerbi\\build_pbip.py aircraft   # opens on another page (its folder name)

Writes powerbi/AccidentDashboard.pbip plus its .SemanticModel (TMDL) and .Report (PBIR)
folders, then open the .pbip in Power BI Desktop and click Refresh. The model imports the
dbo.vw_pbi_* views from sql/07_powerbi_views.sql; change the Server and Database parameters
in Power Query (Transform data > Edit parameters) if yours differ.

Re-running overwrites the generated folders, so make lasting layout changes here, or save
from Power BI Desktop and stop using this script. IDs are derived from names, so
regenerating does not churn them.
"""
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "AccidentDashboard"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
NS = uuid.UUID("5f1d7c1e-2a3b-4c5d-9e8f-a1b2c3d4e5f6")


def tag(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name: str) -> str:
    """Quote a TMDL object name when it is not a plain identifier."""
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


# ---------------------------------------------------------------- semantic model
# table -> (source view, columns, measures). Column: (name, dataType, {property: value}).
HIDDEN = {"isHidden": True}
TABLES = {
    "Accident": ("vw_pbi_accident", [
        ("accident_key", "int64", HIDDEN), ("ev_id", "string", {}), ("ntsb_no", "string", {}),
        ("ev_date", "dateTime", {"formatString": "yyyy-mm-dd"}), ("date_key", "int64", HIDDEN),
        ("ev_country", "string", {}), ("ev_state", "string", {}), ("ev_city", "string", {}),
        ("latitude", "double", {"dataCategory": "Latitude"}), ("longitude", "double", {"dataCategory": "Longitude"}),
        ("is_us", "boolean", {}), ("aircraft_dim_key", "int64", HIDDEN), ("operation_key", "int64", HIDDEN),
        ("phase_key", "int64", HIDDEN), ("wx_cond_key", "int64", HIDDEN), ("light_cond", "string", {}),
        ("damage", "string", {}), ("highest_injury", "string", {}), ("is_fatal", "boolean", {}),
        ("event_fatalities", "int64", {"summarizeBy": "sum"}), ("is_primary_aircraft", "boolean", {}),
        ("defining_event", "string", {}), ("pilot_age", "int64", {}),
        ("pilot_hours_band", "string", {"sortByColumn": "pilot_hours_order"}), ("pilot_hours_order", "int64", HIDDEN),
        ("nearest_airport", "string", {}), ("nearest_airport_name", "string", {}), ("probable_cause", "string", {}),
    ], [
        ("Accidents", "DISTINCTCOUNT(Accident[ev_id])", "#,0"),
        ("Fatal Accidents", "CALCULATE(DISTINCTCOUNT(Accident[ev_id]), Accident[is_fatal] = TRUE())", "#,0"),
        ("Fatal %", "DIVIDE([Fatal Accidents], [Accidents])", "0.0%"),
        ("Fatalities", "CALCULATE(SUM(Accident[event_fatalities]), Accident[is_primary_aircraft] = TRUE())", "#,0"),
        ("Aircraft Involved", "COUNTROWS(Accident)", "#,0"),
        ("Avg Latitude", "AVERAGE(Accident[latitude])", "0.000"),
        ("Avg Longitude", "AVERAGE(Accident[longitude])", "0.000"),
        # blank below 100 registered: a tiny exact-name match (ROBINSON: 2) gives a meaningless rate
        ("Accidents per 1,000 Registered",
         "IF([Registered Aircraft] >= 100, DIVIDE([Accidents], [Registered Aircraft]) * 1000)", "0.0"),
    ]),
    "Calendar": ("vw_pbi_calendar", [
        ("date_key", "int64", HIDDEN), ("full_date", "dateTime", {"formatString": "yyyy-mm-dd", "isKey": True}),
        ("year", "int64", {}), ("quarter", "int64", {}), ("month", "int64", {}), ("decade", "int64", {}),
    ], []),
    "Aircraft": ("vw_pbi_aircraft", [
        ("aircraft_dim_key", "int64", HIDDEN), ("make", "string", {}), ("model", "string", {}),
        ("acft_category", "string", {}), ("num_eng", "int64", {}),
    ], []),
    "Operation": ("vw_pbi_operation", [
        ("operation_key", "int64", HIDDEN), ("far_part", "string", {}), ("operation_name", "string", {}),
        ("is_general_aviation", "boolean", {}),
    ], []),
    "Phase": ("vw_pbi_phase", [
        ("phase_key", "int64", HIDDEN), ("phase_code", "string", {}), ("phase_name", "string", {}),
        ("phase_group", "string", {"sortByColumn": "phase_group_order"}), ("phase_group_order", "int64", HIDDEN),
    ], []),
    "Weather": ("vw_pbi_weather", [
        ("wx_cond_key", "int64", HIDDEN), ("wx_code", "string", {}), ("wx_name", "string", {}),
    ], []),
    "Tag": ("vw_pbi_tag", [
        ("accident_key", "int64", HIDDEN), ("ev_id", "string", HIDDEN), ("is_fatal", "boolean", HIDDEN),
        ("tag", "string", {}),
    ], [
        ("Tagged Accidents", "DISTINCTCOUNT(Tag[ev_id])", "#,0"),
        ("Tagged Fatal %", "DIVIDE(CALCULATE(DISTINCTCOUNT(Tag[ev_id]), Tag[is_fatal] = TRUE()), [Tagged Accidents])", "0.0%"),
    ]),
    "Finding": ("vw_pbi_finding", [
        ("accident_key", "int64", HIDDEN), ("ev_id", "string", HIDDEN), ("finding_category", "string", {}),
        ("finding_description", "string", {}), ("finding_role", "string", {}),
    ], [
        ("Accidents with Finding", "DISTINCTCOUNT(Finding[ev_id])", "#,0"),
    ]),
    "Fleet": ("vw_pbi_fleet", [
        ("make", "string", {}), ("registered_aircraft", "int64", {"summarizeBy": "sum"}),
    ], [
        # no relationship to Aircraft: makes without an exact FAA match would group as a blank row
        ("Registered Aircraft",
         "CALCULATE(SUM(Fleet[registered_aircraft]), TREATAS(VALUES(Aircraft[make]), Fleet[make]))", "#,0"),
    ]),
}
# (from table.column (many side), to table.column (one side))
RELATIONSHIPS = [
    ("Accident.date_key", "Calendar.date_key"),
    ("Accident.aircraft_dim_key", "Aircraft.aircraft_dim_key"),
    ("Accident.operation_key", "Operation.operation_key"),
    ("Accident.phase_key", "Phase.phase_key"),
    ("Accident.wx_cond_key", "Weather.wx_cond_key"),
    ("Tag.accident_key", "Accident.accident_key"),
    ("Finding.accident_key", "Accident.accident_key"),
]


def table_tmdl(table: str) -> str:
    view, columns, measures = TABLES[table]
    out = [f"table {q(table)}", f"\tlineageTag: {tag('table', table)}"]
    if table == "Calendar":
        out.append("\tdataCategory: Time")
    out.append("")
    for name, expr, fmt in measures:
        out += [f"\tmeasure {q(name)} = {expr}", f"\t\tformatString: {fmt}",
                f"\t\tlineageTag: {tag('measure', table, name)}", ""]
    for name, dtype, props in columns:
        summarize = props.get("summarizeBy", "none")
        out += [f"\tcolumn {q(name)}", f"\t\tdataType: {dtype}"]
        if props.get("isKey"):
            out.append("\t\tisKey")
        if props.get("isHidden"):
            out.append("\t\tisHidden")
        for key in ("formatString", "dataCategory", "sortByColumn"):
            if key in props:
                out.append(f"\t\t{key}: {props[key]}")
        out += [f"\t\tlineageTag: {tag('column', table, name)}", f"\t\tsummarizeBy: {summarize}",
                f"\t\tsourceColumn: {name}", "", "\t\tannotation SummarizationSetBy = User", ""]
    out += [
        f"\tpartition {q(table)} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        "\t\t\t\t    Source = Sql.Database(Server, Database),",
        f'\t\t\t\t    Data = Source{{[Schema = "dbo", Item = "{view}"]}}[Data]',
        "\t\t\t\tin",
        "\t\t\t\t    Data",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(out)


def write_model(folder: Path) -> None:
    d = folder / "definition"
    (d / "tables").mkdir(parents=True)
    write_json(folder / "definition.pbism", {
        "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {}})
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1600\n\n", encoding="utf-8")
    order = ["Server", "Database", *TABLES]
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects",
             "\t\treturnErrorValuesAsNull", "",
             "annotation __PBI_TimeIntelligenceEnabled = 0", "",
             f"annotation PBI_QueryOrder = {json.dumps(order, separators=(',', ':'))}", ""]
    model += [f"ref table {q(t)}" for t in TABLES] + [""]
    (d / "model.tmdl").write_text("\n".join(model), encoding="utf-8")
    expressions = []
    for pname, default in (("Server", "localhost"), ("Database", "AviationSafety")):
        expressions += [
            f'expression {pname} = "{default}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
            f"\tlineageTag: {tag('expression', pname)}", "", "\tannotation PBI_ResultType = Text", ""]
    (d / "expressions.tmdl").write_text("\n".join(expressions), encoding="utf-8")
    rels = []
    for src, dst in RELATIONSHIPS:
        rels += [f"relationship {tag('relationship', src, dst)}", f"\tfromColumn: {src}", f"\ttoColumn: {dst}", ""]
    (d / "relationships.tmdl").write_text("\n".join(rels), encoding="utf-8")
    for t in TABLES:
        (d / "tables" / f"{t}.tmdl").write_text(table_tmdl(t), encoding="utf-8")


# ---------------------------------------------------------------- report
def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def measure(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def label(field: dict, text: str) -> dict:
    """Show a field under a readable name in visuals (the model keeps the SQL column name)."""
    return {**field, "_label": text}


def bare(field: dict) -> dict:
    return {k: v for k, v in field.items() if k != "_label"}


def projection(field: dict) -> dict:
    kind = "Column" if "Column" in field else "Measure"
    entity = field[kind]["Expression"]["SourceRef"]["Entity"]
    prop = field[kind]["Property"]
    out = {"field": bare(field), "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if "_label" in field:
        out["displayName"] = field["_label"]
    return out


def visual(name, vtype, x, y, w, h, roles, title=None, sort=None, objects=None) -> dict:
    query = {"queryState": {role: {"projections": [projection(f) for f in fields]} for role, fields in roles.items()}}
    if sort:
        field, direction = sort
        query["sortDefinition"] = {"sort": [{"field": bare(field), "direction": direction}], "isDefaultSort": False}
    body = {"visualType": vtype, "query": query, "drillFilterOtherVisuals": True}
    if objects:
        body["objects"] = objects
    if title:
        body["visualContainerObjects"] = {"title": [{"properties": {
            "show": literal("true"), "text": literal("'" + title.replace("'", "''") + "'")}}]}
    return {
        "$schema": f"{SCHEMA}/item/report/definition/visualContainer/1.4.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "width": w, "height": h},
        "visual": body,
    }


def slicer(name, x, field, title, y=10, w=300, h=70) -> dict:
    # the container title names the slicer; the slicer's own header would repeat the column name
    return visual(name, "slicer", x, y, w, h, {"Values": [field]}, title, objects={
        "data": [{"properties": {"mode": literal("'Dropdown'")}}],
        "header": [{"properties": {"show": literal("false")}}]})


def card(name, x, field, title, y=90, w=300, h=95) -> dict:
    # full numbers ("28,951", not "29K"), and no category label repeating the title
    return visual(name, "card", x, y, w, h, {"Values": [field]}, title, objects={
        "labels": [{"properties": {"labelDisplayUnits": literal("1D")}}],
        "categoryLabels": [{"properties": {"show": literal("false")}}]})


TOP = 95   # first row below the slicers
A = lambda p: col("Accident", p)
ACC, FATAL = measure("Accident", "Accidents"), measure("Accident", "Fatal Accidents")
FPCT = label(measure("Accident", "Fatal %"), "Fatal share")
YEAR, US = label(col("Calendar", "year"), "Year"), label(A("is_us"), "U.S. only")
PHASE = label(col("Phase", "phase_group"), "Phase")
HOURS = label(A("pilot_hours_band"), "Pilot total hours")
STATE, INJURY = label(A("ev_state"), "State"), label(A("highest_injury"), "Highest injury")
OPERATION = label(col("Operation", "operation_name"), "Operation")
MAKE, CATEGORY = label(col("Aircraft", "make"), "Make"), label(col("Aircraft", "acft_category"), "Category")

PAGES = [
    ("overview", "Overview", [
        slicer("s_year", 20, YEAR, "Year"),
        slicer("s_operation", 340, OPERATION, "Operation"),
        slicer("s_us", 660, US, "U.S. only"),
        card("c_acc", 20, ACC, "Accidents"),
        card("c_fatal", 335, FATAL, "Fatal accidents"),
        card("c_deaths", 650, measure("Accident", "Fatalities"), "Fatalities"),
        card("c_pct", 965, FPCT, "Fatal share"),
        visual("v_trend", "lineChart", 20, 200, 760, 500, {"Category": [YEAR], "Y": [ACC, FATAL]},
               "Accidents and fatal accidents by year (latest year is partial)", sort=(YEAR, "Ascending")),
        visual("v_operation", "clusteredBarChart", 800, 200, 460, 500, {"Category": [OPERATION], "Y": [ACC]},
               "Accidents by type of operation", sort=(ACC, "Descending")),
    ]),
    ("phase", "Phase of flight", [
        slicer("s_year", 20, YEAR, "Year"),
        slicer("s_us", 340, US, "U.S. only"),
        visual("v_phase_count", "clusteredBarChart", 20, TOP, 615, 290, {"Category": [PHASE], "Y": [ACC]},
               "Accidents by phase of flight", sort=(PHASE, "Ascending")),
        visual("v_phase_pct", "clusteredBarChart", 645, TOP, 615, 290, {"Category": [PHASE], "Y": [FPCT]},
               "Fatal share by phase of flight", sort=(PHASE, "Ascending")),
        visual("v_phase_table", "tableEx", 20, 400, 1240, 300,
               {"Values": [PHASE, label(col("Phase", "phase_name"), "Detailed phase"), ACC, FATAL, FPCT]},
               "Detailed phases", sort=(ACC, "Descending")),
    ]),
    ("causes", "Causes", [
        slicer("s_year", 20, YEAR, "Year"),
        slicer("s_us", 340, US, "U.S. only"),
        visual("v_tag_count", "clusteredBarChart", 20, TOP, 615, 290,
               {"Category": [label(col("Tag", "tag"), "Tag")], "Y": [measure("Tag", "Tagged Accidents")]},
               "Accidents by narrative tag (keyword rules; undercounts)", sort=(measure("Tag", "Tagged Accidents"), "Descending")),
        visual("v_tag_pct", "clusteredBarChart", 645, TOP, 615, 290,
               {"Category": [label(col("Tag", "tag"), "Tag")], "Y": [label(measure("Tag", "Tagged Fatal %"), "Fatal share")]},
               "Fatal share by narrative tag", sort=(measure("Tag", "Tagged Fatal %"), "Descending")),
        visual("v_finding", "clusteredBarChart", 20, 400, 1240, 300,
               {"Category": [label(col("Finding", "finding_category"), "Finding category")],
                "Y": [measure("Finding", "Accidents with Finding")]},
               "Accidents by NTSB finding category", sort=(measure("Finding", "Accidents with Finding"), "Descending")),
    ]),
    ("aircraft", "Aircraft", [
        slicer("s_year", 20, YEAR, "Year"),
        slicer("s_category", 340, CATEGORY, "Aircraft category"),
        slicer("s_us", 660, US, "U.S. only"),
        visual("v_make_table", "tableEx", 20, TOP, 760, 605,
               {"Values": [MAKE, ACC, measure("Fleet", "Registered Aircraft"),
                           label(measure("Accident", "Accidents per 1,000 Registered"), "Per 1,000 registered")]},
               "Accidents vs. today's registered fleet (exact make-name match; rate shown for 100+ registered)",
               sort=(ACC, "Descending")),
        visual("v_category", "clusteredBarChart", 800, TOP, 460, 605, {"Category": [CATEGORY], "Y": [ACC]},
               "Accidents by aircraft category", sort=(ACC, "Descending")),
    ]),
    ("weather_pilot", "Weather and pilot", [
        slicer("s_year", 20, YEAR, "Year"),
        slicer("s_us", 340, US, "U.S. only"),
        visual("v_wx", "clusteredColumnChart", 20, TOP, 615, 290,
               {"Category": [label(col("Weather", "wx_name"), "Weather")], "Y": [FPCT]},
               "Fatal share by weather conditions", sort=(FPCT, "Descending")),
        visual("v_light", "clusteredColumnChart", 645, TOP, 615, 290,
               {"Category": [label(A("light_cond"), "Light")], "Y": [FPCT]},
               "Fatal share by light conditions", sort=(FPCT, "Descending")),
        visual("v_hours_count", "clusteredColumnChart", 20, 400, 615, 300, {"Category": [HOURS], "Y": [ACC]},
               "Accidents by pilot total flight hours", sort=(HOURS, "Ascending")),
        visual("v_hours_pct", "clusteredColumnChart", 645, 400, 615, 300, {"Category": [HOURS], "Y": [FPCT]},
               "Fatal share by pilot total flight hours", sort=(HOURS, "Ascending")),
    ]),
    ("locations", "Locations", [
        slicer("s_year", 20, YEAR, "Year"),
        slicer("s_state", 340, STATE, "State"),
        slicer("s_injury", 660, INJURY, "Highest injury"),
        visual("v_scatter", "scatterChart", 20, TOP, 1240, 605,
               {"Category": [label(A("accident_key"), "Accident")],
                "X": [label(measure("Accident", "Avg Longitude"), "Longitude")],
                "Y": [label(measure("Accident", "Avg Latitude"), "Latitude")]},
               "Accident locations (longitude vs. latitude; large selections are sampled)"),
    ]),
    ("list", "Accident list", [
        slicer("s_year", 20, YEAR, "Year"),
        slicer("s_state", 340, STATE, "State"),
        slicer("s_part", 660, label(col("Operation", "far_part"), "FAR part"), "FAR part"),
        slicer("s_injury", 980, INJURY, "Highest injury", w=280),
        visual("v_list", "tableEx", 20, TOP, 1240, 605,
               {"Values": [label(A("ev_date"), "Date"), label(A("ntsb_no"), "NTSB no."), STATE,
                           label(A("ev_city"), "City"), MAKE, label(col("Aircraft", "model"), "Model"),
                           label(col("Phase", "phase_name"), "Phase"), INJURY,
                           label(A("event_fatalities"), "Fatalities"), label(A("probable_cause"), "Probable cause")]},
               "Accidents (one row per aircraft)", sort=(A("ev_date"), "Descending")),
    ]),
]


def write_report(folder: Path, active_page: str) -> None:
    d = folder / "definition"
    write_json(folder / "definition.pbir", {
        "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    write_json(d / "version.json", {
        "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    write_json(d / "report.json", {
        "$schema": f"{SCHEMA}/item/report/definition/report/1.2.0/schema.json",
        "themeCollection": {}, "layoutOptimization": "None"})
    write_json(d / "pages" / "pages.json", {
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p[0] for p in PAGES], "activePageName": active_page})
    for page_name, display, visuals in PAGES:
        p = d / "pages" / page_name
        write_json(p / "page.json", {
            "$schema": f"{SCHEMA}/item/report/definition/page/1.3.0/schema.json",
            "name": page_name, "displayName": display, "displayOption": "FitToPage",
            "height": 720, "width": 1280})
        for v in visuals:
            write_json(p / "visuals" / v["name"] / "visual.json", v)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    # optional argument: the page the report opens on (default: the first page)
    active = sys.argv[1] if len(sys.argv) > 1 else PAGES[0][0]
    if active not in [p[0] for p in PAGES]:
        sys.exit(f"unknown page {active!r}; pages: {', '.join(p[0] for p in PAGES)}")
    for suffix in (".SemanticModel", ".Report"):
        shutil.rmtree(ROOT / f"{NAME}{suffix}", ignore_errors=True)
    write_model(ROOT / f"{NAME}.SemanticModel")
    write_report(ROOT / f"{NAME}.Report", active)
    write_json(ROOT / f"{NAME}.pbip", {
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    print(f"wrote {ROOT / (NAME + '.pbip')}")


if __name__ == "__main__":
    main()
