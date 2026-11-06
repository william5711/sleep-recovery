"""Guards against publishing real results by accident."""

import subprocess
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parent.parent


def test_committed_notebook_has_no_outputs():
    notebook = nbformat.read(ROOT / "explore.ipynb", as_version=4)
    with_outputs = [i for i, cell in enumerate(notebook.cells) if cell.get("outputs")]
    assert not with_outputs, (
        "explore.ipynb has saved outputs, which show real data. Run it into private/ instead, "
        "or clear it with: jupyter nbconvert --clear-output --inplace explore.ipynb"
    )


def test_private_folder_is_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert "private/" in ignored
    assert "data/" in ignored


def test_personal_files_are_ignored_by_git():
    # calendar.csv has personal dates and is only kept out by the *.csv rule.
    # The example calendar is meant to be committed.
    def ignored(path):
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0

    assert ignored("calendar.csv")
    assert ignored("data/health.duckdb")
    assert ignored("private/REPORT.md")
    assert not ignored("calendar.example.csv")
