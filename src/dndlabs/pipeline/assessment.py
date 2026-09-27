"""Hit-to-lead assessment of stored datasets."""

import uuid

from dndlabs.assessment.criteria import REQUIRED_DESCRIPTORS, assess
from dndlabs.core.exceptions import ValidationError
from dndlabs.core.protocols import Featurizer, Repositories
from dndlabs.core.schemas import DatasetAssessment, NormalizedRecord, StoredFeatures


class AssessmentService:
    """Assesses a dataset against hit-to-lead criteria, scoped by organization."""

    def __init__(self, repositories: Repositories, featurizer: Featurizer) -> None:
        """Wire the service.

        Args:
            repositories: Storage.
            featurizer: Recomputes descriptors missing from older vectors.
        """
        self._repos = repositories
        self._featurizer = featurizer

    def assess(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> DatasetAssessment:
        """Assess one of the organization's datasets.

        Args:
            org_id: The organization.
            dataset_id: The dataset.

        Returns:
            Potency classes, criteria summaries and per-compound profiles.

        Raises:
            NotFoundError: If the dataset does not exist or belongs to another org.
        """
        records = self._repos.datasets.get(org_id, dataset_id).records
        return self.assess_records(org_id, dataset_id, records)

    def assess_records(
        self, org_id: uuid.UUID, dataset_id: uuid.UUID, records: list[NormalizedRecord]
    ) -> DatasetAssessment:
        """Assess records already loaded from one of the organization's datasets.

        Args:
            org_id: The organization.
            dataset_id: The dataset the records belong to.
            records: Its records.

        Returns:
            Potency classes, criteria summaries and per-compound profiles.
        """
        features = self._repos.features.features_for(org_id, [r.id for r in records])
        # Vectors stored before a descriptor or alerts existed lack them:
        # recompute from the structure (in memory; stored vectors are not rewritten).
        for record in records:
            stored = features.get(record.id)
            complete = (
                stored is not None
                and stored.alerts is not None
                and stored.descriptors.keys() >= REQUIRED_DESCRIPTORS
            )
            if record.canonical_smiles and not complete:
                try:
                    vector = self._featurizer.featurize(record)
                except ValidationError:
                    continue  # unparseable structure: the profile stays without properties
                features[record.id] = StoredFeatures(
                    record_id=record.id, descriptors=vector.descriptors, alerts=vector.alerts
                )
        return assess(dataset_id, records, features)
