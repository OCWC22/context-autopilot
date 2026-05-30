"""Map check names -> classes and build instances."""

from __future__ import annotations

from .base import EngineeringCheck
from .cicd import CICDCheck
from .security import SecurityCheck
from .code_quality import CodeQualityCheck
from .test_execution import TestExecutionCheck
from .dependency_analysis import DependencyAnalysisCheck
from .deployment_validation import DeploymentValidationCheck

REGISTRY: dict[str, type[EngineeringCheck]] = {
    CICDCheck.name: CICDCheck,
    SecurityCheck.name: SecurityCheck,
    CodeQualityCheck.name: CodeQualityCheck,
    TestExecutionCheck.name: TestExecutionCheck,
    DependencyAnalysisCheck.name: DependencyAnalysisCheck,
    DeploymentValidationCheck.name: DeploymentValidationCheck,
}


def build_checks(names, **kw) -> list[EngineeringCheck]:
    out: list[EngineeringCheck] = []
    for n in names:
        cls = REGISTRY.get(n)
        if cls is not None:
            out.append(cls(**kw))
    return out
