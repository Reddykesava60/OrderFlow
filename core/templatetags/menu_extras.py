# core/templatetags/menu_extras.py
import json
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def jsonify(value):
    """Safely encode a Python value as a JSON string for inline JS.
    Marked safe because json.dumps already escapes special chars —
    Django's auto-escaping would corrupt the quotes."""
    return mark_safe(json.dumps(value))

# core/templatetags/menu_extras.py  — add this filter
@register.filter
def get_item(dictionary, key):
    """{{ my_dict|get_item:some_key }}"""
    return dictionary.get(str(key))