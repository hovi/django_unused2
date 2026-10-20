import ast
import importlib.util
import os
from pathlib import Path
from typing import Dict, List, Optional, Union, TypeVar, Type, Set

from django.apps import AppConfig, apps
from django.conf import settings

from django_unused2.dataclasses import (
    StringWithLine,
    Template,
    Python,
    TemplateReference,
    TemplateTokenReference,
    ReferenceType,
)
from django_unused2.template_util import extract_template_references

INSTALLED_PACKAGE_DIRS = {"site-packages", "dist-packages"}


def is_local_path(path: Union[str, Path]) -> bool:
    resolved = Path(path).resolve()
    if INSTALLED_PACKAGE_DIRS.intersection(resolved.parts):
        return False
    return resolved.is_relative_to(Path(settings.BASE_DIR).resolve())


def find_app_templates() -> List[Template]:
    templates: List[Template] = []

    for config in apps.get_app_configs():
        dir_path = os.path.join(str(config.path), "templates")
        templates.extend(
            find_templates_in_directory(
                dir_path, app_config=config, local_app=is_local_path(config.path)
            )
        )
    return templates


T = TypeVar(
    "T", bound=Union[Template, Python]
)  # Ensuring T is bound to our defined classes


def find_in_directory(
    dir_path: str,
    cls: Type[T],
    local_app: bool,
    app_config: Optional["AppConfig"] = None,
) -> List[T]:
    extensions = cls.extensions
    found_items: List[T] = []
    for root, _, files in os.walk(dir_path):
        for file in files:
            extension = os.path.splitext(file)[1]
            if extension in extensions:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, dir_path).replace("\\", "/")
                found_items.append(
                    cls(
                        id=os.path.join(dir_path, relative_path),
                        base_dir=dir_path,
                        relative_path=relative_path,
                        app_config=app_config,
                        local_app=local_app,
                    )  # type: ignore[arg-type]
                )
    return found_items


def find_templates_in_directory(
    dir_path: str, local_app: bool, app_config: Optional[AppConfig] = None
) -> List[Template]:
    return find_in_directory(
        dir_path, cls=Template, app_config=app_config, local_app=local_app
    )


def find_python_in_directory(
    dir_path: str, local_app: bool, app_config: Optional[AppConfig] = None
) -> List[Python]:
    return find_in_directory(
        dir_path, cls=Python, app_config=app_config, local_app=local_app
    )


def find_global_templates() -> List[Template]:
    templates: List[Template] = []

    if settings.TEMPLATES:
        for template_backend in settings.TEMPLATES:
            for directory in template_backend.get("DIRS", []):
                templates.extend(
                    find_templates_in_directory(
                        str(directory), local_app=is_local_path(directory)
                    )
                )

    return templates


def find_py_files() -> List[Python]:
    result: List[Python] = []

    for config in apps.get_app_configs():
        result.extend(
            find_python_in_directory(
                str(config.path),
                local_app=is_local_path(config.path),
                app_config=config,
            )
        )

    # Project-level python files (urls.py, views.py) next to ROOT_URLCONF
    # usually don't belong to any installed app.
    root_urlconf = getattr(settings, "ROOT_URLCONF", None)
    spec = importlib.util.find_spec(root_urlconf) if root_urlconf else None
    if spec and spec.origin:
        found_ids = {python_file.id for python_file in result}
        dir_path = os.path.dirname(spec.origin)
        result.extend(
            python_file
            for python_file in find_python_in_directory(
                dir_path, local_app=is_local_path(dir_path)
            )
            if python_file.id not in found_ids
        )

    return result


def get_normalized_path(base_dir: str, path: str):
    if path.startswith("."):
        return os.path.normpath(os.path.join(base_dir, path)).replace("\\", "/")
    return os.path.normpath(path).replace("\\", "/")


def get_templates_by_relative_path(templates: List[Template]) -> Dict[str, Template]:
    """
    Like Django's template loaders, the first template with a given path wins.
    """
    return {template.relative_path: template for template in reversed(templates)}


def find_template_to_template_references(
    templates: List[Template],
) -> List[TemplateReference]:
    results = []

    templates_by_relative_path = get_templates_by_relative_path(templates)

    for template in templates:
        with open(template.absolute_path, "r", encoding="utf-8") as file:
            contents = file.read()

        template_references: List[TemplateTokenReference] = extract_template_references(
            contents
        )

        for template_reference in template_references:
            reference_normalized_relative = get_normalized_path(
                template.relative_dir_path, template_reference.file_path
            )

            if reference_normalized_relative in templates_by_relative_path:
                target_template = templates_by_relative_path[
                    reference_normalized_relative
                ]
                results.append(
                    TemplateReference(
                        source_id=template.id,
                        target_id=target_template.id,
                        reference_type=template_reference.reference_type,
                        broken=False,
                        line=template_reference.line_number,
                    )
                )
            else:
                results.append(
                    TemplateReference(
                        source_id=template.id,
                        target_id=reference_normalized_relative,
                        reference_type=template_reference.reference_type,
                        broken=True,
                        line=template_reference.line_number,
                    )
                )

    return results


class StringLiteralVisitor(ast.NodeVisitor):
    def __init__(self, suffixes: Optional[Set[str]] = None):
        self.suffixes = suffixes or {".html", ".txt"}
        self.found_strings: List[StringWithLine] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        for suffix in self.suffixes:
            if isinstance(node.value, str) and node.value.endswith(suffix):
                self.found_strings.append(StringWithLine(node.value, node.lineno))
        self.generic_visit(node)


def extract_string_literals(source_code: Union[str, bytes]) -> List[StringWithLine]:
    tree = ast.parse(source_code)
    visitor = StringLiteralVisitor()
    visitor.visit(tree)
    return visitor.found_strings


def find_python_to_template_references(
    templates: List[Template], python_files: List[Python]
) -> List[TemplateReference]:
    used_templates = []

    templates_by_relative_path = get_templates_by_relative_path(templates)

    for python_file in python_files:
        # Read bytes so ast.parse honours the file's encoding declaration.
        with open(python_file.absolute_path, "rb") as file:
            source = file.read()

        try:
            string_references = extract_string_literals(source_code=source)
        except (SyntaxError, ValueError):
            continue

        for string_reference in string_references:
            template = templates_by_relative_path.get(string_reference.value)
            if template:
                used_templates.append(
                    TemplateReference(
                        line=string_reference.line,
                        source_id=python_file.id,
                        target_id=template.id,
                        reference_type=ReferenceType.render,
                    )
                )

    return used_templates


def find_all_references(
    templates: List[Template], python_files: List[Python]
) -> List[TemplateReference]:
    return find_python_to_template_references(
        templates, python_files
    ) + find_template_to_template_references(templates)
