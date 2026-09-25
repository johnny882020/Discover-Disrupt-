# Test Fixtures

| File | Contents |
|---|---|
| `pubchem_properties_12.json` | PUG REST property response for 12 CIDs: 2244, 3672, 5090, 2519, 1983, 4091, 2662, 3386, 156391, 3033, 4485, 3825 |
| `pubchem_name_aspirin.json` | PUG REST response for a name lookup (`aspirin`) |
| `pubchem_not_found.json` | PUG REST `Fault` body returned with HTTP 404 |
| `lab_export_malformed.csv` | Lab export with known defects: 12 records → 5 accepted, 6 rejected, 1 duplicate |
| `data_lake_upload.json` | JSON upload in the `{"records": [...]}` envelope |

The PubChem fixtures use the current PUG REST format. They were generated
offline: the SMILES strings are PubChem's, and the formula, weight, InChI and
InChIKey were computed with RDKit. To replace them with live responses, run:

```bash
python scripts/record_pubchem_fixture.py
```

Then confirm they match the live API:

```bash
DNDLABS_LIVE_TESTS=1 pytest -m live
```

The expected quality report for `lab_export_malformed.csv` is asserted in
`tests/integration/test_pipeline_e2e.py`.
