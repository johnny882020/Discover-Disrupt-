import pytest

from dndlabs.core.protocols import Repositories
from dndlabs.storage.database import create_db_engine, create_schema
from dndlabs.storage.repositories import build_sql_repositories


@pytest.fixture
def repos() -> Repositories:
    engine = create_db_engine("sqlite:///:memory:")
    create_schema(engine)
    return build_sql_repositories(engine)
