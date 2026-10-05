from pathlib import Path

from openpyxl import Workbook

from scripts.run_territorial_ingestion import main


FIXTURES = Path(__file__).parents[1] / "fixtures" / "territorial"


def write_istat_fixture(path: Path) -> None:
    import json

    rows = json.loads((FIXTURES / "istat_rows.json").read_text())
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Official ISTAT fixture"])
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_unified_cli_runs_both_offline_modes_without_network(tmp_path, capsys):
    database_url = f"sqlite:///{tmp_path / 'territorial.db'}"
    raw_path = tmp_path / "raw"
    xlsx = tmp_path / "istat.xlsx"
    write_istat_fixture(xlsx)

    assert (
        main(
            [
                "territories",
                "--fixture",
                str(xlsx),
                "--database-url",
                database_url,
                "--raw-storage-path",
                str(raw_path),
            ]
        )
        == 0
    )
    territories_output = capsys.readouterr().out
    assert '"municipalities_mapped": 2' in territories_output

    assert (
        main(
            [
                "offices",
                "--fixture",
                str(FIXTURES / "dait_mayors.csv"),
                "--database-url",
                database_url,
                "--raw-storage-path",
                str(raw_path),
            ]
        )
        == 0
    )
    offices_output = capsys.readouterr().out
    assert '"mandates_mapped": 2' in offices_output
    assert '"unresolved_people": 2' in offices_output
    assert '"identity_cases": 1' in offices_output


def test_cli_requires_explicit_input_and_territories_before_offices(tmp_path, capsys):
    database_url = f"sqlite:///{tmp_path / 'territorial.db'}"
    raw_path = tmp_path / "raw"
    assert main(["territories", "--database-url", database_url]) == 1
    assert "requires --fixture" in capsys.readouterr().err
    assert (
        main(
            [
                "offices",
                "--fixture",
                str(FIXTURES / "dait_mayors.csv"),
                "--database-url",
                database_url,
                "--raw-storage-path",
                str(raw_path),
            ]
        )
        == 1
    )
    assert "ISTAT territories first" in capsys.readouterr().err
