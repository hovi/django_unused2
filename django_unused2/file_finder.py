import ast
import os
from typing import List, Optional, Union, TypeVar, Type, Set

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


def find_app_templates() -> List[Template]:
    templates: List[Template] = []

    for config in apps.get_app_configs():
        local_app = str(config.path).find(str(settings.BASE_DIR)) > -1
        dir_path = os.path.join(str(config.path), "templates")
        templates.extend(
            find_templates_in_directory(
                dir_path, app_config=config, local_app=local_app
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
    extensions = cls.extensions()
    found_items: List[T] = []
    for root, _, files in os.walk(dir_path):
        for file in files:
            extension = os.path.splitext(file)[1]
            if extension in extensions:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, dir_path).replace("\\", "/")
                found_items.append(
                    cls(
                        id=file_path,
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
                local_app = directory.find(str(settings.BASE_DIR)) > -1
                templates.extend(
                    find_templates_in_directory(directory, local_app=local_app)
                )

    return templates


def find_py_files(exclude_dirs: Optional[List[str]] = None) -> List[Python]:
    exclude_dirs = exclude_dirs or [os.path.join("example", "server", "tests")]

    python_extensions = ["py"]
    result: List[Python] = []

    for config in apps.get_app_configs():
        local_app = str(config.path).find(str(settings.BASE_DIR)) > -1
        dir_path = str(config.path)
        new_files = []
        for root, dirs, files in os.walk(dir_path):
            if any(exclude_dir in root for exclude_dir in exclude_dirs):
                print(f"excluding: {root}")
                continue
            for file in files:
                filename, extension = os.path.splitext(file)
                if extension[1:] in python_extensions:
                    absolute_path = os.path.join(root, file).replace("\\", "/")
                    new_files.append(
                        Python(
                            id=absolute_path,
                            base_dir=dir_path,
                            relative_path=os.path.relpath(absolute_path, dir_path),
                            app_config=config,
                            local_app=local_app,
                        )
                    )
            result.extend(new_files)
    return result


def get_normalized_path(base_dir: str, path: str):
    if path.startswith("."):
        return os.path.normpath(os.path.join(base_dir, path))
    return os.path.normpath(path)


def find_template_to_template_references(
    templates: List[Template],
) -> List[TemplateReference]:
    results = []

    templates_by_relative_path = {
        template.relative_path: template for template in templates
    }

    for template in templates:
        with open(template.absolute_path, "r") as file:
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
        self.suffixes = suffixes or set(Template.extensions())
        self.found_strings: List[StringWithLine] = []

    def visit_Str(self, node: ast.Str) -> None:
        for suffix in self.suffixes:
            if node.s.endswith(suffix):
                self.found_strings.append(StringWithLine(node.s, node.lineno))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        for suffix in self.suffixes:
            if isinstance(node.value, str) and node.value.endswith(suffix):
                self.found_strings.append(StringWithLine(node.value, node.lineno))
        self.generic_visit(node)


def extract_string_literals(source_code: str) -> List[StringWithLine]:
    tree = ast.parse(source_code)
    visitor = StringLiteralVisitor()
    visitor.visit(tree)
    return visitor.found_strings


def find_python_to_template_references(
    templates: List[Template], python_files: List[Python]
) -> List[TemplateReference]:
    used_templates = []

    for python_file in python_files:
        with open(python_file.absolute_path, "r") as file:
            source = file.read()

        string_references = extract_string_literals(source_code=source)
        for template in templates:
            for string_reference in string_references:
                if string_reference.value == template.relative_path:
                    used_templates.append(
                        TemplateReference(
                            line=string_reference.line,
                            source_id=python_file.absolute_path,
                            target_id=template.absolute_path,
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
