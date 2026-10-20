import contextlib
import io
import ntpath
import os
import warnings
from pathlib import Path
from unittest import mock

import django
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

from django_unused2.dataclasses import (
    AnalysisResult,
    Template,
    TemplateFilterOptions,
)
from django_unused2.file_finder import (
    extract_string_literals,
    find_all_references,
    find_app_templates,
    find_global_templates,
    find_in_directory,
    find_python_in_directory,
    find_templates_in_directory,
)
from django_unused2.filter import analyze_references, run_analysis
from django_unused2.graph import generate_dot
from django_unused2.output import print_referenced_by
from tests.template_test_util import TemplateTestCase

TESTS_DIR = settings.BASE_DIR


class TestKnownIssues(TemplateTestCase):
    def analyze(self) -> AnalysisResult:
        templates = find_templates_in_directory(self.test_dir, local_app=True)
        python_files = find_python_in_directory(self.test_dir, local_app=True)
        references = find_all_references(templates=templates, python_files=python_files)
        return analyze_references(
            references=references, templates=templates, python_files=python_files
        )

    def test_deep_include_chain_is_used(self):
        # view -> t0 -> t1 -> ... -> t5
        for i in range(5):
            self.fc(f"t{i}.html", f"{{% include 't{i + 1}.html' %}}")
        self.fc("t5.html", "")
        self.fc("view.py", "render('t0.html')")

        analysis = self.analyze()

        self.assertEqual([], analysis.unused_filenames)

    def test_global_template_dirs_as_path(self):
        self.fc("templates/home.html", "")

        with override_settings(
            TEMPLATES=[
                {
                    "BACKEND": "django.template.backends.django.DjangoTemplates",
                    "DIRS": [Path(self.test_dir) / "templates"],
                }
            ]
        ):
            templates = find_global_templates()

        self.assertEqual(["home.html"], [t.relative_path for t in templates])

    def test_template_graph_with_str_base_dir(self):
        with override_settings(
            BASE_DIR=self.test_dir, INSTALLED_APPS=["django_unused2"]
        ):
            call_command("unused", "template_graph")

        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "unused.dot")))
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "cytoscape.json")))

    def test_variable_include_is_not_broken(self):
        self.fc(
            "page.html",
            """
{% include widget_template %}
{% include widget_template with title="Hello" %}
""",
        )
        self.fc("view.py", "render('page.html')")

        analysis = self.analyze()

        self.assertEqual([], analysis.broken_references)

    def test_variable_extends_is_not_broken(self):
        self.fc("page.html", "{% extends base_template|default:'base.html' %}")
        self.fc("base.html", "")
        self.fc("view.py", "render('page.html')")

        analysis = self.analyze()

        self.assertEqual([], analysis.broken_references)

    @override_settings(
        # .../lib/pythonX.Y, which contains site-packages/django
        BASE_DIR=str(Path(django.__file__).parents[2]),
        INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.admin"],
    )
    def test_virtualenv_inside_base_dir_is_not_local(self):
        # A project with an in-project .venv has its site-packages under BASE_DIR.
        templates = find_app_templates()

        self.assertTrue(templates)
        self.assertEqual([], [t.relative_path for t in templates if t.local_app])

    @override_settings(
        # ".../tests/app" is a string prefix of ".../tests/apps/one_template"
        BASE_DIR=os.path.join(TESTS_DIR, "app"),
        INSTALLED_APPS=["tests.apps.one_template"],
    )
    def test_base_dir_string_prefix_is_not_local(self):
        templates = find_app_templates()

        self.assertEqual([False], [t.local_app for t in templates])

    @override_settings(
        INSTALLED_APPS=[],
        ROOT_URLCONF="tests.apps.project_level.urls",
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [os.path.join(TESTS_DIR, "apps", "project_level", "templates")],
            }
        ],
    )
    def test_template_referenced_from_project_urls(self):
        result = run_analysis(TemplateFilterOptions())

        self.assertEqual([], result.unused_filenames)

    @override_settings(
        INSTALLED_APPS=["tests.apps.override_local", "tests.apps.override_vendor"],
    )
    def test_first_installed_app_overrides_template(self):
        # Django resolves "override_vendor/base.html" to override_local's copy,
        # so the vendor copy is the one that is never used.
        result = run_analysis(TemplateFilterOptions())

        self.assertEqual(
            ["tests.apps.override_vendor"],
            [t.app_config.name for t in result.never_referenced_templates],
        )

    def test_print_referenced_by_python_source(self):
        self.fc("page.html", "")
        self.fc("view.py", "render('page.html')")
        analysis = self.analyze()
        template = analysis.templates[0]

        with contextlib.redirect_stdout(io.StringIO()):
            print_referenced_by(template, analysis.references, analysis.templates_by_id)

    def test_windows_template_id_matches_absolute_path(self):
        walk_result = [("C:\\proj\\templates\\sub", [], ["page.html"])]
        with mock.patch("os.path", ntpath), mock.patch(
            "os.walk", return_value=walk_result
        ):
            [template] = find_in_directory(
                "C:\\proj\\templates", cls=Template, local_app=True
            )
            absolute_path = template.absolute_path

        self.assertEqual(template.id, absolute_path)

    def test_python_syntax_error_does_not_abort(self):
        self.fc("page.html", "")
        self.fc("view.py", "render('page.html')")
        self.fc("broken.py", "def broken(:\n")

        analysis = self.analyze()

        self.assertEqual([], analysis.unused_filenames)

    def test_string_literals_without_deprecation_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            strings = extract_string_literals("render('page.html')")

        self.assertEqual(["page.html"], [s.value for s in strings])

    def test_dot_output_escapes_quotes(self):
        template = Template(
            id='/t/a"b.html',
            base_dir="/t",
            relative_path='a"b.html',
            app_config=None,
            local_app=True,
        )

        dot = generate_dot(AnalysisResult(templates=[template]))

        self.assertIn('"/t/a\\"b.html" [label="a\\"b.html"', dot)
