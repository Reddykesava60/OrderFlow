# core/templatetags/menu_extras.py
import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def jsonify(value):
    """Safely encode a Python value as a JSON string for inline JS.
    Escapes HTML-dangerous characters so the output is safe inside
    <script> blocks independent of upstream sanitisation.
    Marked safe because json.dumps + our escaping handles all
    special chars — Django's auto-escaping would corrupt the quotes."""
    serialized = json.dumps(value)
    # Escape characters that could break out of a <script> block or
    # interfere with HTML parsing.  The replacements produce valid JSON
    # (Unicode escape sequences) that JavaScript decodes transparently.
    serialized = serialized.replace('&', r'\u0026')
    serialized = serialized.replace('<', r'\u003c')
    serialized = serialized.replace('>', r'\u003e')
    return mark_safe(serialized)

# core/templatetags/menu_extras.py  — add this filter
@register.filter
def get_item(dictionary, key):
    """{{ my_dict|get_item:some_key }}"""
    return dictionary.get(str(key))