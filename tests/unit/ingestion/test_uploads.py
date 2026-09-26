import uuid

import pytest
from tests.fakes import FakeMappingTemplates, FakeUploads

from dndlabs.core.exceptions import IngestionError, NotFoundError
from dndlabs.core.schemas import (
    ColumnRole,
    MappingTemplateCreate,
    SourceSpec,
    SourceType,
    UploadFormat,
)
from dndlabs.ingestion.uploads import PREVIEW_ROWS, UploadConnector, UploadLimits, UploadService

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
CSV = b"Compound,Structure,IC50,Unit,Notes\nA-1,CCO,12,nM,first\nA-2,c1ccccc1,3,uM,second\n"


@pytest.fixture
def uploads() -> FakeUploads:
    return FakeUploads()


@pytest.fixture
def service(uploads: FakeUploads) -> UploadService:
    return UploadService(
        uploads, FakeMappingTemplates(), UploadLimits(max_bytes=10_000, max_rows=50)
    )


def test_store_parses_hashes_and_previews(service: UploadService) -> None:
    preview = service.store(ORG, "lab.csv", CSV)
    assert preview.upload.format is UploadFormat.CSV
    assert preview.upload.size_bytes == len(CSV)
    assert len(preview.upload.sha256) == 64
    assert preview.columns == ["Compound", "Structure", "IC50", "Unit", "Notes"]
    assert preview.row_count == 2
    assert preview.rows[0]["Structure"] == "CCO"
    assert preview.suggested_mapping == {
        "Unit": ColumnRole.ACTIVITY_UNIT,
        "Structure": ColumnRole.SMILES,  # detected from content
    }  # "Compound" is ambiguous (a name or an id), so the user maps it
    assert preview.template is None


def test_preview_is_limited_to_the_first_rows(service: UploadService) -> None:
    data = ("smiles\n" + "CCO\n" * (PREVIEW_ROWS + 5)).encode()
    preview = service.store(ORG, "many.csv", data)
    assert (len(preview.rows), preview.row_count) == (PREVIEW_ROWS, PREVIEW_ROWS + 5)


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("empty.csv", b"", "empty"),
        ("big.csv", b"smiles\n" + b"C\n" * 6000, "limit is 10000"),
        ("doc.pdf", b"%PDF", "unsupported file type"),
        ("rows.csv", b"smiles\n" + b"C\n" * 51, "limit is 50"),
    ],
)
def test_bad_files_are_rejected_before_storage(
    service: UploadService, uploads: FakeUploads, name: str, data: bytes, message: str
) -> None:
    with pytest.raises(IngestionError, match=message):
        service.store(ORG, name, data)
    assert uploads.items == {}


def test_stored_upload_can_be_previewed_again_only_by_its_org(service: UploadService) -> None:
    upload_id = service.store(ORG, "lab.csv", CSV).upload.id
    assert service.preview(ORG, upload_id).row_count == 2
    with pytest.raises(NotFoundError):
        service.preview(OTHER_ORG, upload_id)


def test_saved_template_is_suggested_for_matching_files(service: UploadService) -> None:
    mapping = {
        "Structure": ColumnRole.SMILES,
        "IC50": ColumnRole.ACTIVITY_VALUE,
        "Unit": ColumnRole.ACTIVITY_UNIT,
        "Notes": ColumnRole.IGNORE,
    }
    saved = service.save_template(
        ORG, MappingTemplateCreate(name=" Plate reader ", mapping=mapping)
    )
    assert saved.name == "Plate reader"

    preview = service.store(ORG, "lab.csv", CSV)
    assert preview.template == saved
    assert preview.suggested_mapping == mapping

    other = service.store(OTHER_ORG, "lab.csv", CSV)
    assert other.template is None  # templates are per organization

    assert [t.name for t in service.list_templates(ORG)] == ["Plate reader"]
    service.delete_template(ORG, saved.id)
    assert service.list_templates(ORG) == []
    with pytest.raises(NotFoundError):
        service.delete_template(ORG, saved.id)


def _spec(upload_id: uuid.UUID, mapping: dict[str, ColumnRole]) -> SourceSpec:
    return SourceSpec(source=SourceType.UPLOAD, upload_id=upload_id, column_mapping=mapping)


async def _records(connector: UploadConnector, org: uuid.UUID, spec: SourceSpec) -> list:  # type: ignore[type-arg]
    return [r async for r in connector.fetch_for_org(org, spec)]


async def test_connector_applies_the_run_mapping(
    service: UploadService, uploads: FakeUploads
) -> None:
    upload_id = service.store(ORG, "lab.csv", CSV).upload.id
    spec = _spec(
        upload_id,
        {
            "Compound": ColumnRole.SOURCE_RECORD_ID,
            "Structure": ColumnRole.SMILES,
            "IC50": ColumnRole.ACTIVITY_VALUE,
            "Unit": ColumnRole.ACTIVITY_UNIT,
        },
    )
    records = await _records(UploadConnector(uploads), ORG, spec)
    assert [(r.source_record_id, r.smiles, r.activity_value, r.activity_unit) for r in records] == [
        ("A-1", "CCO", "12", "nM"),
        ("A-2", "c1ccccc1", "3", "uM"),
    ]
    assert records[0].source is SourceType.UPLOAD
    assert records[0].extra == {"Notes": "first"}


async def test_connector_is_org_scoped_and_checks_columns(
    service: UploadService, uploads: FakeUploads
) -> None:
    upload_id = service.store(ORG, "lab.csv", CSV).upload.id
    connector = UploadConnector(uploads)
    with pytest.raises(NotFoundError):
        await _records(connector, OTHER_ORG, _spec(upload_id, {"Structure": ColumnRole.SMILES}))
    with pytest.raises(IngestionError, match="no column"):
        await _records(connector, ORG, _spec(upload_id, {"Missing": ColumnRole.SMILES}))
    with pytest.raises(IngestionError, match="upload spec"):
        await _records(connector, ORG, SourceSpec(source=SourceType.CSV, csv_path="x.csv"))


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        (None, "requires upload_id and column_mapping"),
        ({"A": ColumnRole.NAME}, "needs a SMILES or InChI column"),
        ({"A": ColumnRole.SMILES, "B": ColumnRole.SMILES}, "one column only"),
    ],
)
def test_upload_spec_validation(mapping: dict[str, ColumnRole] | None, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SourceSpec(source=SourceType.UPLOAD, upload_id=uuid.uuid4(), column_mapping=mapping)


def test_ignored_columns_may_repeat() -> None:
    SourceSpec(
        source=SourceType.UPLOAD,
        upload_id=uuid.uuid4(),
        column_mapping={"A": ColumnRole.SMILES, "B": ColumnRole.IGNORE, "C": ColumnRole.IGNORE},
    )
