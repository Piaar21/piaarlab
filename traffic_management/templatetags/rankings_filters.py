# traffic_management/templatetags/custom_filters.py

from django import template
import builtins

register = template.Library()

@register.filter
def subtract(value, arg):
    try:
        return int(value) - int(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def abs(value):
    try:
        return builtins.abs(int(value))
    except (ValueError, TypeError):
        return ''

@register.filter
def map(value, arg):
    return [getattr(item, arg) if hasattr(item, arg) else item[int(arg)] for item in value]

@register.filter
def intcomma(value):
    try:
        value = int(value)
        return f"{value:,}"
    except (ValueError, TypeError):
        return value
    
@register.filter(name='add_class')
def add_class(field, css_class):
    return field.as_widget(attrs={'class': css_class})

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


register = template.Library()

@register.filter
def get_item(dictionary, key):
    """사전에서 key에 해당하는 값을 반환합니다."""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return ''