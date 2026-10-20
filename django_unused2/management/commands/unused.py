import json
import os
import sys
from argparse import ArgumentParser
from typing import Any, Dict

from django.conf import settings
from django.core.management.base import BaseCommand

from django_unused2.filter import TemplateFilterOptions, run_analysis
from django_unused2.graph import generate_dot, generate_cytoscape_json
from django_unused2.output import print_unreferenced_templates, print_broken_references


class Command(BaseCommand):
    help = "Lists all unused template files."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "unused_type",
            type=str,
            nargs="?",
            default="templates",
            choices=["templates", "template_graph"],
            help="templates (default) lists unused templates, template_graph writes unused.dot and cytoscape.json",
        )
        parser.add_argument(
            "-xa",
            "--excluded-apps",
            type=str,
            nargs="*",
            help="List of apps to exclude from the search",
            dest="excluded_apps",
        )
        parser.add_argument(
            "-xd",
            "--excluded-template-dirs",
            type=str,
            nargs="*",
            help="List of template directories to exclude from the search",
            dest="excluded_template_dirs",
        )
        parser.add_argument(
            "-xt",
            "--excluded-templates",
            type=str,
            nargs="*",
            help="List of specific templates to exclude from the search",
            dest="excluded_templates",
        )
        parser.add_argument(
            "-c",
            "--config",
            type=str,
            help="Path to a JSON configuration file",
            dest="config_path",
        )

    def handle(self, *args: Any, **options: dict[str, Any]):
        unused_type = options["unused_type"]
        filter_options = get_filter_options(options)

        if unused_type == "templates":
            result = run_analysis(filter_options)
            print_unreferenced_templates(
                analysis_result=result, base_dir=settings.BASE_DIR
            )
            print_broken_references(result.broken_references, settings.BASE_DIR)
            if not result:
                sys.exit(1)
        elif unused_type == "template_graph":
            result = run_analysis(filter_options)
            with open(os.path.join(settings.BASE_DIR, "unused.dot"), "w") as f:
                f.write(generate_dot(result))
            with open(os.path.join(settings.BASE_DIR, "cytoscape.json"), "w") as f:
                f.write(generate_cytoscape_json(result))


def get_filter_options(options: Dict[str, Any]) -> TemplateFilterOptions:
    config_path = options.get("config_path")

    if config_path:
        with open(config_path, "r", encoding="utf-8") as config_file:
            config_data = json.load(config_file)
            return TemplateFilterOptions(
                excluded_apps=config_data.get("excluded_apps", []),
                excluded_template_dirs=config_data.get("excluded_template_dirs", []),
                excluded_templates=config_data.get("excluded_templates", []),
            )

    return TemplateFilterOptions(
        excluded_apps=options.get("excluded_apps", []),
        excluded_template_dirs=options.get("excluded_template_dirs", []),
        excluded_templates=options.get("excluded_templates", []),
    )
