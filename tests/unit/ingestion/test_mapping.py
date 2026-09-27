import uuid

from dndlabs.core.schemas import ColumnRole, MappingTemplate
from dndlabs.ingestion.mapping import suggest_mapping
from dndlabs.ingestion.tabular import Table

ORG = uuid.uuid4()


def _table(columns: list[str], *rows: list[str]) -> Table:
    return Table(columns=columns, rows=[dict(zip(columns, r, strict=True)) for r in rows])


def test_known_header_aliases_are_mapped() -> None:
    table = _table(["Compound_ID", "SMILES", "MW", "Standard_Value", "Units", "Notes"])
    mapping, template = suggest_mapping(table, [])
    assert template is None
    assert mapping == {
        "Compound_ID": ColumnRole.SOURCE_RECORD_ID,
        "SMILES": ColumnRole.SMILES,
        "MW": ColumnRole.MOLECULAR_WEIGHT,
        "Standard_Value": ColumnRole.ACTIVITY_VALUE,
        "Units": ColumnRole.ACTIVITY_UNIT,
    }  # "Notes" stays unmapped (kept as extra data)


def test_headers_with_spaces_and_punctuation_are_mapped() -> None:
    table = _table(["Compound ID", "Canonical SMILES", "Activity Value", "Unit (text)"])
    mapping, _ = suggest_mapping(table, [])
    assert mapping == {
        "Compound ID": ColumnRole.SOURCE_RECORD_ID,
        "Canonical SMILES": ColumnRole.SMILES,
        "Activity Value": ColumnRole.ACTIVITY_VALUE,
    }


def test_a_role_is_suggested_for_one_column_only() -> None:
    mapping, _ = suggest_mapping(_table(["smiles", "canonical_smiles"]), [])
    assert mapping == {"smiles": ColumnRole.SMILES}


def test_structure_columns_are_recognized_by_content() -> None:
    table = _table(
        ["Structure", "Label", "Potency"],
        ["CC(=O)Oc1ccccc1C(=O)O", "aspirin", "12"],
        ["CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "caffeine", "3.5"],
        ["c1ccccc1", "benzene", "7"],
    )
    mapping, _ = suggest_mapping(table, [])
    assert mapping == {"Structure": ColumnRole.SMILES}


def test_a_structure_column_with_some_invalid_smiles_is_still_recognized() -> None:
    table = _table(
        ["Code", "Mol"], ["A-1", "CC(=O)Oc1ccccc1C(=O)O"], ["A-2", "C1CC("], ["A-3", "[Na+].[Cl-]"]
    )
    mapping, _ = suggest_mapping(table, [])
    assert mapping == {"Mol": ColumnRole.SMILES}  # "A-1" ids are SMILES-shaped but do not parse


def test_inchi_and_inchikey_are_recognized_by_content() -> None:
    table = _table(
        ["A", "B"],
        ["InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3", "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"],
    )
    mapping, _ = suggest_mapping(table, [])
    assert mapping["A"] is ColumnRole.INCHI


def test_numbers_and_words_are_not_mistaken_for_smiles() -> None:
    table = _table(["ids", "words"], ["1", "C"], ["22", "CC"], ["3.5", "hello there"], ["4", "N"])
    mapping, _ = suggest_mapping(table, [])
    assert "ids" not in mapping
    assert "words" not in mapping  # 3 of 4 parse (< 80%)


def test_content_detection_only_runs_without_a_structure_header() -> None:
    table = _table(["smiles", "Other"], ["CCO", "c1ccccc1"])
    mapping, _ = suggest_mapping(table, [])
    assert mapping == {"smiles": ColumnRole.SMILES}


def test_a_matching_template_wins_and_the_most_specific_one_is_used() -> None:
    small = MappingTemplate(org_id=ORG, name="small", mapping={"Struct": ColumnRole.SMILES})
    large = MappingTemplate(
        org_id=ORG,
        name="large",
        mapping={"Struct": ColumnRole.SMILES, "Val": ColumnRole.ACTIVITY_VALUE},
    )
    other = MappingTemplate(org_id=ORG, name="other", mapping={"Missing": ColumnRole.SMILES})
    table = _table(["Struct", "Val", "smiles"])
    mapping, template = suggest_mapping(table, [small, other, large])
    assert template == large
    assert mapping == {"Struct": ColumnRole.SMILES, "Val": ColumnRole.ACTIVITY_VALUE}


def test_new_structure_headers_are_mapped() -> None:
    table = _table(["MolFile", "PubChem CID", "ChEMBL ID", "Lookup Name"])
    mapping, _ = suggest_mapping(table, [])
    assert mapping == {
        "MolFile": ColumnRole.MOL_BLOCK,
        "PubChem CID": ColumnRole.PUBCHEM_CID,
        "ChEMBL ID": ColumnRole.CHEMBL_ID,
        "Lookup Name": ColumnRole.LOOKUP_NAME,
    }


def test_mol_blocks_and_chembl_ids_are_recognized_by_content() -> None:
    block = "\n  RDKit\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\nM  END\n"
    table = _table(["Structure", "Ref"], [block, "CHEMBL25"], [block, "chembl113"])
    mapping, _ = suggest_mapping(table, [])
    assert mapping == {"Structure": ColumnRole.MOL_BLOCK, "Ref": ColumnRole.CHEMBL_ID}


def test_names_and_cids_are_never_suggested_from_content() -> None:
    # A lookup sends values to PubChem; internal codes must never go by default.
    table = _table(["Compound", "Number"], ["aspirin", "2244"], ["caffeine", "2519"])
    mapping, _ = suggest_mapping(table, [])
    assert mapping == {}


def test_an_identifier_header_does_not_stop_the_search_for_a_structure_column() -> None:
    table = _table(["InChIKey", "Structure"], ["BSYNRYMUTXBXSQ-UHFFFAOYSA-N", "CCO"])
    mapping, _ = suggest_mapping(table, [])
    assert mapping == {"InChIKey": ColumnRole.INCHIKEY, "Structure": ColumnRole.SMILES}
