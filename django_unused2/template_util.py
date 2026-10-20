from typing import List, Optional

from django.template.base import Token, TokenType, Lexer

from django_unused2.dataclasses import TemplateTokenReference, ReferenceType


def extract_template_reference(token: Token) -> Optional[str]:
    """
    Return the template path of an include/extends tag, or None when the
    template is given by a variable or expression.
    """
    bits = token.split_contents()
    if len(bits) < 2:
        return None
    path = bits[1]
    if len(path) >= 2 and path[0] == path[-1] and path[0] in "'\"":
        return path[1:-1]
    return None


def extract_template_references(template_text: str) -> List[TemplateTokenReference]:
    """
    Extract all template references from a template string with its type.
    """
    lexer = Lexer(template_text)

    tokens = lexer.tokenize()
    result = []
    for token in tokens:
        contents = token.contents
        if token.token_type == TokenType.BLOCK and (
            contents.startswith("include ") or contents.startswith("extends ")
        ):
            reference_type: ReferenceType = ReferenceType.unknown
            if contents.startswith("include "):
                reference_type = ReferenceType.include
            if contents.startswith("extends "):
                reference_type = ReferenceType.extends
            relative_path = extract_template_reference(token)
            if not relative_path:
                continue
            result.append(
                TemplateTokenReference(
                    relative_path,
                    line_number=token.lineno,
                    reference_type=reference_type,
                )
            )
    return result
