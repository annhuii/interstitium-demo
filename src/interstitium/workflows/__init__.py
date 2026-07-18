"""The registry. Adding a workflow means adding it here -- nothing else.

The runtime guards, the PHI scan, and the registry-wide safety tests all apply
to whatever is in this list, so a new entry inherits them rather than
reimplementing them.

`UnclassifiedLoopWorkflow` is the fallback and must stay registered: it is what
makes the claim "no loop is unowned" true for signals nobody anticipated.
"""

from typing import List

from ..runtime import Workflow
from .ama import HighRiskAMAWorkflow
from .culture import CultureResultWorkflow
from .fallback import UnclassifiedLoopWorkflow
from .intake import DischargeIntakeWorkflow
from .lab_integrity import LabResultIntegrityWorkflow
from .radiology import RadiologyAddendumWorkflow
from .symptoms import SymptomFollowUpWorkflow

#: Specialised workflows. Order is not significant; a signal may match several.
SPECIALISTS: List[Workflow] = [
    DischargeIntakeWorkflow(),
    HighRiskAMAWorkflow(),
    CultureResultWorkflow(),
    LabResultIntegrityWorkflow(),
    RadiologyAddendumWorkflow(),
    SymptomFollowUpWorkflow(),
]

REGISTRY: List[Workflow] = SPECIALISTS + [UnclassifiedLoopWorkflow()]

__all__ = [
    "REGISTRY",
    "SPECIALISTS",
    "DischargeIntakeWorkflow",
    "HighRiskAMAWorkflow",
    "CultureResultWorkflow",
    "LabResultIntegrityWorkflow",
    "RadiologyAddendumWorkflow",
    "SymptomFollowUpWorkflow",
    "UnclassifiedLoopWorkflow",
]
