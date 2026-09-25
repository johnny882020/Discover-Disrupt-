# Test fixtures

| File | What it is |
|---|---|
| `pubchem_properties_12.json` | PUG REST `PropertyTable` response for 12 CIDs (2244, 3672, 5090, 2519, 1983, 4091, 2662, 3386, 156391, 3033, 4485, 3825). |
| `pubchem_name_aspirin.json` | PUG REST response for `/compound/name/aspirin/property/.../JSON`. |
| `pubchem_not_found.json` | PUG REST `Fault` body returned with HTTP 404 for an unknown name. |
| `lab_export_malformed.csv` | Synthetic ELN/instrument export with known defects (see `tests/integration/test_pipeline_e2e.py` for the expected quality report). |
| `data_lake_upload.json` | Generic JSON upload in the `{"records": [...]}` envelope. |

The PubChem fixtures follow the current PUG REST response format (`SMILES` /
`ConnectivitySMILES` keys). They were produced offline because the build
sandbox's network policy blocks `pubchem.ncbi.nlm.nih.gov`: structures are
the canonical PubChem SMILES for each CID, and formula / weight / InChI /
InChIKey were computed with RDKit. Re-record them against the live API with
`python scripts/record_pubchem_fixture.py` when network access is available;
`tests/integration/test_pubchem_live.py` (opt-in) checks live parity.
