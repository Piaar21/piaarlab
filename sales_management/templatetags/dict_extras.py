# dict_extras.py
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    dictionary[key] 접근을 템플릿에서 가능하게 하는 필터
    """
    if dictionary is None:
        return None
    return dictionary.get(key)