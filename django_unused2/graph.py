import json

from django_unused2.dataclasses import AnalysisResult


def dot_quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def generate_dot(analysis_result: AnalysisResult) -> str:
    lines = ["digraph G {"]

    # Add nodes for Python files and Templates
    for py in analysis_result.python_files:
        lines.append(
            f"    {dot_quote(py.id)} [label={dot_quote(py.relative_path)}, shape=box];"
        )
    for tmpl in analysis_result.templates:
        lines.append(
            f"    {dot_quote(tmpl.id)} [label={dot_quote(tmpl.relative_path)}, shape=ellipse];"
        )

    # Add edges for references
    for ref in analysis_result.references:
        color = "red" if ref.broken else "black"
        lines.append(
            f'    {dot_quote(ref.source_id)} -> {dot_quote(ref.target_id)} [label="{ref.reference_type.name}", color="{color}"];'
        )

    lines.append("}")

    return "\n".join(lines)


def generate_cytoscape_json(analysis_result: AnalysisResult) -> str:
    elements = []
    never_used_ids = {t.id for t in analysis_result.never_referenced_templates}

    node_ids = set()

    for ref in analysis_result.references:
        if ref.broken:
            continue
        node_ids.add(ref.source_id)
        node_ids.add(ref.target_id)

    for ref in analysis_result.references:
        if ref.broken:
            continue
        if ref.source_id not in never_used_ids and ref.target_id not in never_used_ids:
            elements.append(
                {
                    "data": {
                        "source": ref.source_id,
                        "target": ref.target_id,
                        "label": ref.reference_type.name,
                        "line": ref.line,
                    }
                }
            )

    for ref in analysis_result.references:
        if ref.broken:
            continue
        if not (
            ref.source_id not in never_used_ids and ref.target_id not in never_used_ids
        ):
            elements.append(
                {
                    "data": {
                        "source": ref.source_id,
                        "target": ref.target_id,
                        "label": ref.reference_type.name,
                        "line": ref.line,
                    }
                }
            )

    for py in analysis_result.python_files:
        if py.id not in node_ids:
            continue
        app = ""
        if py.app_config:
            app = py.app_config.name

        elements.append(
            {
                "data": {
                    "id": py.id,
                    "label": py.relative_path,
                    "type": "python",
                    "app": app,
                }
            }
        )

    for tmpl in analysis_result.templates:
        if tmpl.id not in node_ids:
            continue
        used = tmpl.id not in never_used_ids
        app = ""
        if tmpl.app_config:
            app = tmpl.app_config.name
        elements.append(
            {
                "data": {
                    "id": tmpl.id,
                    "label": tmpl.relative_path,
                    "type": "template",
                    "app": app,
                    "used": used,
                }
            }
        )

    return json.dumps(elements, indent=4)
