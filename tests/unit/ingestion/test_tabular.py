import io

import pytest
from openpyxl import Workbook  # type: ignore[import-untyped]
from rdkit import Chem

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import UploadFormat
from dndlabs.ingestion.tabular import read_delimited, read_table, upload_format

LIMIT = 1000


@pytest.mark.parametrize(
    ("name", "fmt"),
    [
        ("a.csv", UploadFormat.CSV),
        ("A.CSV", UploadFormat.CSV),
        ("notes.txt", UploadFormat.CSV),
        ("a.tsv", UploadFormat.TSV),
        ("a.tab", UploadFormat.TSV),
        ("book.xlsx", UploadFormat.XLSX),
        ("mols.sdf", UploadFormat.SDF),
        ("mols.sd", UploadFormat.SDF),
    ],
)
def test_upload_format_by_extension(name: str, fmt: UploadFormat) -> None:
    assert upload_format(name) is fmt


@pytest.mark.parametrize("name", ["a.xls", "a.pdf", "noextension"])
def test_unsupported_extensions_are_rejected(name: str) -> None:
    with pytest.raises(IngestionError, match="unsupported file type"):
        upload_format(name)


def test_csv_with_bom_sniffs_the_delimiter_and_drops_blank_rows() -> None:
    data = "﻿smiles;name\nCCO;ethanol\n;\nc1ccccc1;benzene\n".encode()
    table = read_table(data, UploadFormat.CSV, LIMIT)
    assert table.columns == ["smiles", "name"]
    assert table.rows == [
        {"smiles": "CCO", "name": "ethanol"},
        {"smiles": "c1ccccc1", "name": "benzene"},
    ]


def test_windows_1252_text_is_decoded() -> None:
    data = "name,smiles\nCaf\xe9,CCO\n".encode("cp1252")
    assert read_table(data, UploadFormat.CSV, LIMIT).rows == [{"name": "Café", "smiles": "CCO"}]


def test_tsv_uses_tabs() -> None:
    data = b"smiles\tnote\nCCO\ta, b\n"
    assert read_table(data, UploadFormat.TSV, LIMIT).rows == [{"smiles": "CCO", "note": "a, b"}]


def test_ragged_rows_are_rejected() -> None:
    with pytest.raises(IngestionError, match="cannot parse"):
        read_delimited("a,b\n1,2,3\n")


def test_row_limit_is_enforced() -> None:
    data = ("smiles\n" + "C\n" * 5).encode()
    with pytest.raises(IngestionError, match="limit is 4"):
        read_table(data, UploadFormat.CSV, 4)


def _xlsx(rows: list[list[object]]) -> bytes:
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_xlsx_first_non_empty_row_is_the_header() -> None:
    data = _xlsx(
        [
            [None, None],
            ["Compound", "SMILES", "IC50", None, "Compound"],
            ["aspirin", "CC(=O)Oc1ccccc1C(=O)O", 1500.0, None, "dup"],
            [None, None, None],
            ["ethanol", "CCO", 2.5],
        ]
    )
    table = read_table(data, UploadFormat.XLSX, LIMIT)
    assert table.columns == ["Compound", "SMILES", "IC50", "column_4", "Compound_2"]
    assert table.rows[0]["IC50"] == "1500"  # whole-number floats lose ".0"
    assert table.rows[1] == {
        "Compound": "ethanol",
        "SMILES": "CCO",
        "IC50": "2.5",
        "column_4": "",
        "Compound_2": "",
    }


def test_corrupt_xlsx_is_rejected() -> None:
    with pytest.raises(IngestionError, match="Excel"):
        read_table(b"not a workbook", UploadFormat.XLSX, LIMIT)


def _sdf(entries: list[tuple[str, dict[str, str]]]) -> bytes:
    buffer = io.StringIO()
    writer = Chem.SDWriter(buffer)
    for smiles, props in entries:
        mol = Chem.MolFromSmiles(smiles)
        mol.SetProp("_Name", props.pop("_Name", ""))
        for key, value in props.items():
            mol.SetProp(key, value)
        writer.write(mol)
    writer.close()
    return buffer.getvalue().encode()


def test_sdf_rows_hold_smiles_name_and_data_fields() -> None:
    data = _sdf(
        [
            ("CCO", {"_Name": "ethanol", "IC50_nM": "12"}),
            ("c1ccccc1", {"_Name": "benzene", "target": "EGFR"}),
        ]
    )
    table = read_table(data, UploadFormat.SDF, LIMIT)
    assert table.columns == ["smiles", "name", "IC50_nM", "target"]
    assert table.rows == [
        {"smiles": "CCO", "name": "ethanol", "IC50_nM": "12", "target": ""},
        {"smiles": "c1ccccc1", "name": "benzene", "IC50_nM": "", "target": "EGFR"},
    ]


def test_sdf_without_molecules_is_rejected() -> None:
    with pytest.raises(IngestionError, match="no molecules"):
        read_table(b"", UploadFormat.SDF, LIMIT)


def test_file_without_columns_is_rejected() -> None:
    with pytest.raises(IngestionError, match="no columns"):
        read_table(_xlsx([]), UploadFormat.XLSX, LIMIT)


def test_sdf_structure_rdkit_rejects_is_kept_for_validation_to_report() -> None:
    pentavalent = """
     RDKit          2D

  2  1  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  5  0  0  0  0  0  0
    1.0000    0.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  2  0
M  CHG  1   2   3
M  END
$$$$
"""
    table = read_table(pentavalent.encode(), UploadFormat.SDF, LIMIT)
    assert len(table.rows) == 1
    assert table.rows[0]["smiles"]  # present, so validation reports it rather than dropping it
