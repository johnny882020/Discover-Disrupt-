"""Structural alerts: substructures that flag a compound as a liability.

Three families, each reported with the atoms it matched:

- **PAINS** (pan-assay interference compounds; Baell & Holloway, *J. Med.
  Chem.* 2010): frequent false positives in screening assays. RDKit's
  catalog of 480 filters.
- **Brenk** (Brenk et al., *ChemMedChem* 2008): unwanted, reactive or
  unstable groups. RDKit's catalog of 105 filters.
- **Reactive metabolite**: groups that form reactive metabolites, a leading
  cause of idiosyncratic toxicity (Stepan et al., *Chem. Res. Toxicol.*
  2011; Kalgutkar et al., *Curr. Drug Metab.* 2005). Curated here; each
  pattern is tested against positive and negative examples.

PAINS and Brenk use RDKit's bundled catalogs rather than a copy of the
SMARTS, so they track the published lists; RDKit has no reactive-metabolite
catalog, hence the curated table below. The assessment makes criteria of
PAINS and reactive metabolites only; Brenk alerts are reported for review.
"""

from rdkit import Chem
from rdkit.Chem import FilterCatalog

from dndlabs.core.schemas import AlertFamily, StructuralAlert

#: Reactive-metabolite alerts: name -> SMARTS patterns (any may match).
#: Several patterns cover alternative notations or isomers (nitro charge
#: forms, ortho/para quinones and their precursors).
REACTIVE_METABOLITE_ALERTS: dict[str, tuple[str, ...]] = {
    "Aniline (primary aromatic amine)": ("[NX3;H2;!$(N[#6]=[#7,#8,#16])]c",),
    "Nitroaromatic": ("c[NX3+](=O)[O-]", "c[NX3](=O)=O"),
    "Thiophene": ("c1ccsc1",),
    "Furan": ("c1ccoc1",),
    # Two non-aromatic N without double bonds: hydrazones and pyrazoles don't match.
    "Hydrazine or hydrazide": ("[NX3;!$(N=*);!a][NX3;!$(N=*);!a]",),
    # Non-aromatic atoms only: aryl ketones and aromatic pyranones don't match.
    "Michael acceptor (alpha,beta-unsaturated carbonyl)": ("[CX3;!a]=[CX3;!a][CX3;!a]=[OX1]",),
    "Epoxide or aziridine": ("[C;r3]1[O,N;r3][C;r3]1",),
    "Quinone": (
        "[#6X3]1(=[OX1])[#6X3]=,:[#6X3][#6X3](=[OX1])[#6X3]=,:[#6X3]1",
        "[#6X3]1(=[OX1])[#6X3](=[OX1])[#6X3]=,:[#6X3][#6X3]=,:[#6X3]1",
    ),
    "Catechol or hydroquinone (quinone precursor)": (
        "[OH]c:c[OH]",
        "[OH]c1:c:c:c([OH]):c:c1",
    ),
    "Alkyl halide": ("[CX4;!$(C(F)F)][Cl,Br,I]",),
    "Aldehyde": ("[CX3H1](=O)[#6]",),
    "Thiourea": ("[NX3][CX3](=[SX1])[NX3]",),
    "Terminal alkyne": ("[CX2]#[CX2H1]",),
    "Methylenedioxyphenyl": ("c1cc2OCOc2cc1",),
    "2-Aminothiazole": ("[NX3;H2,H1]c1ncc[s]1",),
}


def _catalog(
    which: FilterCatalog.FilterCatalogParams.FilterCatalogs,
) -> FilterCatalog.FilterCatalog:
    """Load one of RDKit's filter catalogs."""
    params = FilterCatalog.FilterCatalogParams()
    params.AddCatalog(which)
    return FilterCatalog.FilterCatalog(params)


class AlertScanner:
    """Finds PAINS, Brenk and reactive-metabolite alerts in a molecule."""

    def __init__(self) -> None:
        """Load the catalogs and compile the reactive-metabolite patterns once."""
        catalogs = FilterCatalog.FilterCatalogParams.FilterCatalogs
        self._catalogs = (
            (AlertFamily.PAINS, _catalog(catalogs.PAINS)),
            (AlertFamily.BRENK, _catalog(catalogs.BRENK)),
        )
        self._reactive = {
            name: [Chem.MolFromSmarts(pattern) for pattern in patterns]
            for name, patterns in REACTIVE_METABOLITE_ALERTS.items()
        }

    def scan(self, mol: Chem.Mol) -> list[StructuralAlert]:
        """Return every alert the molecule triggers, catalog order.

        Args:
            mol: A sanitized molecule parsed from the record's canonical SMILES.

        Returns:
            The alerts, each with the atom indices it matched.
        """
        alerts: list[StructuralAlert] = []
        # One alert per matching filter or named pattern; its atoms are the
        # union of every match, which is what the UI highlights.
        for family, catalog in self._catalogs:
            for entry in catalog.GetMatches(mol):
                matches = entry.GetFilterMatches(mol)
                atoms = {pair[1] for match in matches for pair in match.atomPairs}
                alerts.append(
                    StructuralAlert(family=family, name=entry.GetDescription(), atoms=sorted(atoms))
                )
        for name, patterns in self._reactive.items():
            atoms = {
                i
                for pattern in patterns
                for match in mol.GetSubstructMatches(pattern)
                for i in match
            }
            if atoms:
                alerts.append(
                    StructuralAlert(
                        family=AlertFamily.REACTIVE_METABOLITE, name=name, atoms=sorted(atoms)
                    )
                )
        return alerts
