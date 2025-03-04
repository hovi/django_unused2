from typing import Dict

from django.core.management import CommandError
from django.core.management.base import BaseCommand
from django.template import Template as DjangoTemplate, Origin

from django_unused2.check_template_util import (
    analyze_variables_in_includes,
    print_analysis_results,
    TemplateIncludeInfo,
    analyze_for_includes,
)
from django_unused2.file_finder import find_app_templates


class Command(BaseCommand):
    help = "Check syntax of all Django templates by loading them separately"

    def add_arguments(self, parser):
        parser.add_argument(
            "-I",
            "--check-include-params",
            action="store_true",
            default=False,
            help="Check parameters in IncludeNode",
        )

    def handle(self, *args, **options):
        success = 0
        error = 0

        check_include_params = options["check_include_params"]

        template_include_info_by_relative_path: Dict[str, TemplateIncludeInfo] = {}
        for template in find_app_templates():
            if not template.local_app:
                continue
            elif "site-packages" in template.absolute_path:
                continue
            path = template.absolute_path
            try:
                with open(path, "r") as f:
                    template_content = f.read()
                django_template = DjangoTemplate(
                    template_content,
                    origin=Origin(name="name", template_name=template.relative_path),
                )
                if check_include_params:
                    result = analyze_for_includes(
                        template=template, django_template=django_template
                    )
                    template_include_info_by_relative_path[template.relative_path] = (
                        result
                    )
                    pass
                success += 1
            except Exception as e:
                error += 1
                self.stdout.write(
                    self.style.ERROR(f"An error occurred with template {path}:\n{e}\n")
                )
        if check_include_params:
            analysis_result = analyze_variables_in_includes(
                template_include_info_by_relative_path
            )
            print_analysis_results(analysis_result)
            if len(analysis_result) > 0:
                self.stdout.write(
                    self.style.ERROR(
                        f"{len(analysis_result)} include errors in templates."
                    )
                )
        if error > 0:
            raise CommandError(
                f"Template check complete. {error} errors found. {success} templates passed."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Template check complete. {success} templates passed."
                )
            )
