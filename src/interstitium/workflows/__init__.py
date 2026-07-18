"""The registry. Adding a workflow means adding it here -- nothing else.

The runtime guards, the PHI scan, and the registry-wide safety tests all apply
to whatever is in this list, so a new entry inherits them rather than
reimplementing them.
"""

from typing import List

from ..runtime import Workflow
from .ama import HighRiskAMAWorkflow
from .culture import CultureResultWorkflow
from .intake import DischargeIntakeWorkflow
from .radiology import RadiologyAddendumWorkflow
from .symptoms import SymptomFollowUpWorkflow

REGISTRY: List[Workflow] = [
    DischargeIntakeWorkflow(),
    HighRiskAMAWorkflow(),
    CultureResultWorkflow(),
    RadiologyAddendumWorkflow(),
    SymptomFollowUpWorkflow(),
]

__all__ = [
    "REGISTRY",
    "DischargeIntakeWorkflow",
    "HighRiskAMAWorkflow",
    "CultureResultWorkflow",
    "RadiologyAddendumWorkflow",
    "SymptomFollowUpWorkflow",
]
