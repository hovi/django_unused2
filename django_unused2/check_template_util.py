from dataclasses import dataclass, field
from typing import Set, List, Dict, Optional

from django.template import Template as DjangoTemplate
from django.template.loader_tags import IncludeNode

from django_unused2.dataclasses import Template


@dataclass
class TemplateIncludeInfo:
    template: Template
    django_template: DjangoTemplate
    variables_needed: Set[str]
    includes: List[IncludeNode]


@dataclass
class IncludeAnalysisResult:
    """
    Dataclass to hold the analysis result for each include statement.
    """

    template_path: str
    include_relative_path: Optional[str]
    missing_only_keyword: bool
    line_number: Optional[int]
    missing_vars: Set[str] = field(default_factory=set)
    """
    To finish this, need to also do optional variables.
    """
    unused_vars: Set[str] = field(default_factory=set)

    def __str__(self):
        result = [f"{self.template_path}:"]
        if self.missing_vars:
            result.append(
                f"line {self.line_number}: missing variables: "
                f"{', '.join(self.missing_vars)}"
            )

        if self.missing_only_keyword:
            result.append(f"line {self.line_number}: is missing 'only' keyword.")
        return "\n".join(result)


def analyze_variables_in_includes(
    template_include_info_by_relative_path: Dict[str, TemplateIncludeInfo]
) -> List[IncludeAnalysisResult]:
    """
    Analyzes templates and returns structured data about missing variables and 'only' keyword issues in includes.
    """
    analysis_results = []

    for template_path, template_info in template_include_info_by_relative_path.items():
        for include_node in template_info.includes:
            include_relative_path = (
                str(include_node.template.token)[1:-1]
                if hasattr(include_node, "template")
                else None
            )
            token = getattr(include_node, "token", None)
            line_number = token.lineno if token else None

            result = IncludeAnalysisResult(
                template_path=template_path,
                include_relative_path=include_relative_path,
                line_number=line_number,
                missing_only_keyword=not include_node.isolated_context,
            )

            if hasattr(include_node, "extra_context"):
                extra_context = include_node.extra_context
                passed_vars = set(extra_context.keys())

                include_relative_path = str(include_node.template.token)[1:-1]
                template = template_include_info_by_relative_path.get(
                    include_relative_path, None
                )

                if template:
                    variables_needed = template.variables_needed
                    result.missing_vars = variables_needed - passed_vars
                    result.unused_vars = passed_vars - variables_needed

            if not include_node.isolated_context:
                result.missing_only_keyword = True

            if (
                result.missing_vars
                or result.missing_only_keyword
                and template_info.template.relative_path.startswith("frontend/")
                and not template_info.template.relative_path.startswith("frontend/inc/")
                and not include_relative_path.startswith("frontend/inc/")
            ):
                analysis_results.append(result)

    return analysis_results


def print_analysis_results(analysis_results: List[IncludeAnalysisResult]):
    for result in analysis_results:
        print(result)
        print()
