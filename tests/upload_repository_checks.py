"""Behavioural checks for the upload repositories, shared by the SQLite and PostgreSQL suites."""

import pytest

from dndlabs.core.exceptions import NotFoundError
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import ColumnRole, MappingTemplate, Organization, Upload, UploadFormat

DATA = b"smiles\nCCO\n" + bytes(range(256))  # binary-safe round trip


def check_uploads(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    other = repos.organizations.create(Organization(name="OtherCo"))
    upload = repos.uploads.create(
        Upload(
            org_id=org.id,
            filename="lab.csv",
            format=UploadFormat.CSV,
            size_bytes=len(DATA),
            sha256="a" * 64,
        ),
        DATA,
    )
    fetched = repos.uploads.get(org.id, upload.id)
    assert (fetched.id, fetched.filename, fetched.format, fetched.size_bytes) == (
        upload.id,
        "lab.csv",
        UploadFormat.CSV,
        len(DATA),
    )
    assert repos.uploads.get_data(org.id, upload.id) == DATA
    with pytest.raises(NotFoundError):
        repos.uploads.get(other.id, upload.id)
    with pytest.raises(NotFoundError):
        repos.uploads.get_data(other.id, upload.id)

    repos.datasets.delete_org_data(org.id)  # privacy deletion removes uploads
    with pytest.raises(NotFoundError):
        repos.uploads.get(org.id, upload.id)


def check_mapping_templates(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    other = repos.organizations.create(Organization(name="OtherCo"))
    first = repos.mapping_templates.create(
        MappingTemplate(org_id=org.id, name="Reader", mapping={"S": ColumnRole.SMILES})
    )
    repos.mapping_templates.create(
        MappingTemplate(org_id=org.id, name="Archive", mapping={"I": ColumnRole.INCHI})
    )
    replacement = repos.mapping_templates.create(
        MappingTemplate(
            org_id=org.id,
            name="Reader",
            mapping={"S": ColumnRole.SMILES, "V": ColumnRole.ACTIVITY_VALUE},
        )
    )
    repos.mapping_templates.create(
        MappingTemplate(org_id=other.id, name="Reader", mapping={"X": ColumnRole.SMILES})
    )

    templates = repos.mapping_templates.list_templates(org.id)
    assert [t.name for t in templates] == ["Archive", "Reader"]
    reader = templates[1]
    assert reader.id == replacement.id != first.id  # same name replaces
    assert reader.mapping == {"S": ColumnRole.SMILES, "V": ColumnRole.ACTIVITY_VALUE}

    with pytest.raises(NotFoundError):
        repos.mapping_templates.delete(other.id, reader.id)
    repos.mapping_templates.delete(org.id, reader.id)
    assert [t.name for t in repos.mapping_templates.list_templates(org.id)] == ["Archive"]
    with pytest.raises(NotFoundError):
        repos.mapping_templates.delete(org.id, reader.id)


UPLOAD_CHECKS = (check_uploads, check_mapping_templates)
