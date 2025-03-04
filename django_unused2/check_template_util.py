from dataclasses import dataclass, field
from typing import Set, List, Generator, Dict, Optional

from django.template import Template as DjangoTemplate
from django.template.base import NodeList, Variable, FilterExpression, Node
from django.template.defaulttags import (
    ForNode,
    IfNode,
    TemplateLiteral,
    URLNode,
    WithNode,
    CsrfTokenNode,
)
from django.template.exceptions import TemplateSyntaxError
from django.template.loader_tags import IncludeNode
from django.templatetags.i18n import TranslateNode

from django_unused2.dataclasses import Template


@dataclass
class TemplateIncludeInfo:
    template: Template
    django_template: DjangoTemplate
    variables_needed: Set[str]
    includes: List[IncludeNode]


def analyze_for_includes(
    template: Template, django_template: DjangoTemplate
) -> TemplateIncludeInfo:
    return TemplateIncludeInfo(
        template=template,
        django_template=django_template,
        variables_needed=extract_variables_needed(django_template=django_template),
        includes=extract_includes(django_template),
    )


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
                and (
                    include_relative_path
                    and not include_relative_path.startswith("frontend/inc/")
                )
            ):
                analysis_results.append(result)

    return analysis_results


def print_analysis_results(analysis_results: List[IncludeAnalysisResult]):
    for result in analysis_results:
        print(result)
        print()


class UnexpectedExpressionTypeError(Exception):
    """Custom exception raised when an unexpected expression type is encountered."""

    pass


def yield_nodes(django_template: DjangoTemplate) -> Generator[Node, None, None]:
    """
    A generator function that yields nodes from the DjangoTemplate object.
    Traverses all nodes in the template, including nested nodes.
    """

    def traverse_nodelist(nodelist: NodeList):
        for node in nodelist:
            yield node
            for attr in [
                "nodelist",
                "nodelist_true",
                "nodelist_false",
                "nodelist_loop",
                "nodelist_empty",
            ]:
                if hasattr(node, attr):
                    child_nodelist = getattr(node, attr)
                    yield from traverse_nodelist(child_nodelist)

    yield from traverse_nodelist(django_template.nodelist)


def strip_variable(variable: str) -> str:
    variable = variable.split(".")[0]
    variable = variable.split("|")[0]
    return variable


def extract_variables_from_filter_expression(expression: FilterExpression) -> Set[str]:
    if expression.var and hasattr(expression.var, "lookups") and expression.var.lookups:
        result = strip_variable(expression.var.lookups[0])
        if result in {"True", "False"}:
            return set()
        return {result}
    return set()


def extract_includes(django_template: DjangoTemplate) -> List[IncludeNode]:
    includes = []
    for node in yield_nodes(django_template):
        if isinstance(node, IncludeNode):
            includes.append(node)
    return includes


def extract_variables_from_expression(
    expression, ignore_template_literals: bool = False
) -> Set[str]:
    """
    Recursively extract variables from an expression (FilterExpression, Variable, TemplateLiteral, Operator).
    """
    variables: set[str] = set()
    if not expression:
        return variables

    if isinstance(expression, Variable):
        variables.add(strip_variable(expression.var))
    elif isinstance(expression, FilterExpression):
        variables.update(extract_variables_from_filter_expression(expression))

    elif isinstance(expression, TemplateLiteral):
        if (
            isinstance(expression.value, FilterExpression)
            and not ignore_template_literals
        ):
            variables.update(extract_variables_from_filter_expression(expression.value))

    elif hasattr(expression, "first") and hasattr(expression, "second"):
        if hasattr(expression, "is_not") and expression.is_not():
            variables.update(extract_variables_from_expression(expression.first))
        else:
            variables.update(extract_variables_from_expression(expression.first))
            if expression.second:
                variables.update(extract_variables_from_expression(expression.second))

    else:
        raise UnexpectedExpressionTypeError(
            f"Unexpected expression type: {type(expression)} ({expression}"
        )

    return variables


def extract_variables_from_ifnode(if_node: IfNode) -> Set[str]:
    """
    Extracts the variables used in the condition(s) of an IfNode.
    """
    variables_needed = set()

    for condition_tuple in if_node.conditions_nodelists:
        expression = condition_tuple[0]
        variables_needed.update(
            extract_variables_from_expression(expression, ignore_template_literals=True)
        )

    return variables_needed


def extract_variables_needed(django_template: DjangoTemplate) -> Set[str]:
    """
    Analyzes a DjangoTemplate object and returns a set of variables needed for rendering,
    including variables used in loops and include tags.
    """

    def traverse_nodes(nodelist: NodeList, local_variables: Set[str]) -> Set[str]:
        variables_needed = set()
        for node in nodelist:
            if isinstance(node, CsrfTokenNode):
                variables_needed.add("csrf_token")

            if isinstance(node, IncludeNode):
                for var in node.extra_context.values():
                    if isinstance(var, FilterExpression):
                        variables_needed.update(
                            extract_variables_from_filter_expression(var)
                        )

            if isinstance(node, WithNode):
                for key, var in node.extra_context.items():
                    local_variables.add(key)
                    if isinstance(var, FilterExpression):
                        variables_needed.update(
                            extract_variables_from_filter_expression(var)
                        )

            if isinstance(node, TranslateNode):
                if node.asvar:
                    local_variables.add(node.asvar)

            if hasattr(node, "filter_expression"):
                if node.filter_expression.var and node.filter_expression.var.lookups:
                    variables_needed.add(
                        strip_variable(node.filter_expression.var.lookups[0])
                    )

            if isinstance(node, ForNode):
                if hasattr(node, "sequence"):
                    sequence_var = node.sequence.token
                    variables_needed.add(strip_variable(sequence_var))
                    loop_copy = local_variables.copy()
                    loop_copy.update(node.loopvars)
                    variables_needed.update(
                        traverse_nodes(node.nodelist_empty, local_variables=loop_copy)
                    )
                    variables_needed.update(
                        traverse_nodes(node.nodelist_loop, local_variables=loop_copy)
                    )

            if isinstance(node, URLNode):
                if node.asvar:
                    local_variables.add(node.asvar)
                for arg in node.args:
                    if isinstance(arg, Variable):
                        variables_needed.add(strip_variable(arg.var))
                    elif isinstance(arg, FilterExpression):
                        variables_needed.update(
                            extract_variables_from_filter_expression(arg)
                        )
                    else:
                        raise TemplateSyntaxError(
                            f"Unexpected argument type: {type(arg)} ({arg})"
                        )

                for kwarg_value in node.kwargs.values():
                    if isinstance(kwarg_value, Variable):
                        variables_needed.add(strip_variable(kwarg_value.var))
                    elif isinstance(kwarg_value, FilterExpression):
                        variables_needed.update(
                            extract_variables_from_filter_expression(kwarg_value)
                        )
                    else:
                        raise TemplateSyntaxError(
                            f"Unexpected argument type: {type(kwarg_value)} ({kwarg_value})"
                        )

            if isinstance(node, IfNode):
                if_variables = extract_variables_from_ifnode(node)
                variables_needed.update(if_variables)

            for attr in ["nodelist", "nodelist_true", "nodelist_false"]:
                if hasattr(node, attr):
                    child_nodelist = getattr(node, attr)
                    variables_needed.update(
                        traverse_nodes(
                            child_nodelist, local_variables=local_variables.copy()
                        )
                    )

        return variables_needed - local_variables

    try:
        return traverse_nodes(django_template.nodelist, {"forloop"})
    except AttributeError as e:
        raise TemplateSyntaxError(f"Error analyzing template: {e}")
