from recovery import build
from recovery.simulator import simulate_export


def test_simulated_export_builds_end_to_end(tmp_path):
    export = simulate_export(tmp_path / "sample")
    con = build(export, tmp_path / "demo.duckdb", calendar=None)
    days, first, last = con.execute("SELECT count(*), min(date), max(date) FROM daily").fetchone()
    assert (str(first), str(last)) == ("2026-06-04", "2026-11-01")
    assert days == 151

    # Each night is written twice, and only v2 should survive.
    assert con.execute("SELECT count(*) FROM sleeps").fetchone()[0] > 2 * 150
    assert con.execute("SELECT max(nap_count) FROM daily").fetchone() == (1,)
    assert con.execute("SELECT count(DISTINCT sleep_algorithm) FROM daily").fetchone() == (1,)

    locations = dict(con.execute("SELECT location, count(*) FROM daily GROUP BY 1").fetchall())
    assert set(locations) == {"Taiwan", "US"}
    assert con.execute("SELECT count(*) FROM daily WHERE steps_source <> 'Fitbit Air'").fetchone() == (0,)


def test_simulated_export_is_reproducible(tmp_path):
    a = simulate_export(tmp_path / "a", seed=3)
    b = simulate_export(tmp_path / "b", seed=3)
    for path in a.rglob("*.csv"):
        assert path.read_text() == (b / path.relative_to(a)).read_text()
