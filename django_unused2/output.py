import os
from typing import List, Dict

from colorama import init, Fore

from django_unused2.dataclasses import (
    ReferenceType,
    TemplateReference,
    Template,
    AnalysisResult,
)

init(autoreset=True)

reference_type_colors = {
    ReferenceType.include: Fore.CYAN,
    ReferenceType.extends: Fore.LIGHTBLUE_EX,
    ReferenceType.unknown: Fore.RED,
    ReferenceType.render: Fore.MAGENTA,
}


def print_unreferenced_templates(analysis_result: AnalysisResult, base_dir: str):
    templates = analysis_result.never_referenced_templates
    references = analysis_result.references
    if not templates:
        print(Fore.GREEN + "No unreferenced templates found.")
        return

    # Group templates by AppConfig name
    grouped_templates: Dict[str, List] = {}
    for template in templates:
        if not template.local_app:
            continue
        app_config_name = (
            template.app_config.name if template.app_config else "No AppConfig"
        )
        if app_config_name not in grouped_templates:
            grouped_templates[app_config_name] = []
        grouped_templates[app_config_name].append(template)

    # Print the grouped templates
    print(Fore.YELLOW + "\nTemplates Never Referenced by Python files:")
    for app_config_name, templates in grouped_templates.items():
        print(Fore.CYAN + f"\nAppConfig: {app_config_name}")
        for template in templates:
            print(Fore.MAGENTA + f"{template.relative_path}")
            print_referenced_by(
                template, references, templates_by_id=analysis_result.templates_by_id
            )


def print_referenced_by(
    template: Template,
    references: List[TemplateReference],
    templates_by_id: Dict[str, Template],
):
    reference_chains = get_reference_chain(
        template_id=template.id, references=references, chain=[]
    )

    def rel_path(template_reference: TemplateReference) -> str:
        source = templates_by_id.get(template_reference.source_id)
        # Sources that aren't templates are python files.
        relative_path = source.relative_path if source else template_reference.source_id
        return f"{Fore.WHITE}{relative_path} ({reference_type_colors.get(template_reference.reference_type, Fore.WHITE)}{template_reference.reference_type.value}{Fore.WHITE} at {Fore.GREEN}{template_reference.line}{Fore.WHITE})"

    if len(reference_chains) > 0:
        print("Referenced by:\n")
        for rc in reference_chains:
            print("\t -> " + " -> ".join([rel_path(chain) for chain in rc]))
        print()


def get_reference_chain(
    template_id: str,
    references: List[TemplateReference],
    chain: List[TemplateReference],
) -> List[List[TemplateReference]]:
    direct_referrals = [
        r for r in references if r.target_id == template_id and r not in chain
    ]

    results = []
    for dr in direct_referrals:
        results.extend(
            get_reference_chain(
                template_id=dr.source_id, references=references, chain=chain + [dr]
            )
        )
    if not results and chain:
        return [chain]
    return results


def print_broken_references(references: List[TemplateReference], base_dir: str):
    if not references:
        print(Fore.GREEN + "No broken references found.")
        return

    print(Fore.RED + "\nBroken References Found:")
    for ref in references:
        source_path = os.path.relpath(ref.source_id, base_dir)
        target_path = os.path.relpath(ref.target_id, base_dir)
        ref_type_color = reference_type_colors.get(ref.reference_type, Fore.WHITE)
        print(
            f"{Fore.BLUE}{source_path} "
            f"{ref_type_color}{ref.reference_type.value} "
            f"{Fore.BLUE}{target_path} "
            f"{Fore.YELLOW}at line "
            f"{Fore.GREEN}{ref.line}"
        )
