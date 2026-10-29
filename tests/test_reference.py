"""reference/ga_activity_bts_table_2_14.csv and its loader."""
from load_ga_hours import DEFAULT_PATH, read_rows


def test_reference_file_loads():
    rows = {r[0]: r for r in read_rows(DEFAULT_PATH)}
    assert len(rows) == 38
    assert rows[2024][1:5] == (24_813_299, 1126, 182, 305)   # hours stored as whole hours
    assert rows[2011][1] is None                             # no FAA estimate that year
    assert all(1975 <= y <= 2100 for y in rows)


def test_published_rates_fall_in_a_plausible_range():
    for year, hours, accidents, fatal, deaths, _ in read_rows(DEFAULT_PATH):
        if hours:
            assert 3 < 100_000 * accidents / hours < 15, year
            assert 0.5 < 100_000 * fatal / hours < 2.5, year
        assert fatal < accidents and deaths >= fatal
