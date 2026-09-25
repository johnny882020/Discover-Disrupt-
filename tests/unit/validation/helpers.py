from dndlabs.core.schemas import NormalizedRecord, RawRecord, SourceType
from dndlabs.validation.validator import seed_record

ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"
ASPIRIN_KEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
ASPIRIN_INCHI = "InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)"
CAFFEINE = "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"
CAFFEINE_AROMATIC = "Cn1cnc2c1c(=O)n(C)c(=O)n2C"


def raw(sid: str = "1", **fields: object) -> RawRecord:
    return RawRecord.model_validate({"source": SourceType.CSV, "source_record_id": sid, **fields})


def seed(r: RawRecord) -> NormalizedRecord:
    return seed_record(r)
