# encoding: utf-8
import time, json
from datetime import datetime, timezone

from django import template
from django.utils.html import format_html #, escape

register = template.Library()

@register.simple_tag
def icon_name(obj, name=None):
    if not name:
        name = obj.name
    color, icon = '#FF0000', '&#31;'
    if obj.icon:
        color, icon = obj.color, obj.icon.html
    result = f"""<span style="color:{color}">{icon}</span><span>&nbsp;{name}</span>"""
    return format_html(result)


@register.simple_tag
def x_range(start, end=None, step=1):
    """
    Usage:
    {% x_range 1 5 as my_range %}
    ou
    {% x_range 0 10 2 as my_range %}
    Retourne une liste Python similaire à range(start, end, step).
    """
    try:
        # convertir en entiers
        if end is None:
            # seul un argument passé -> range(0, start)
            start = int(start)
            seq = list(range(start))
        else:
            start = int(start)
            end = int(end)
            step = int(step)
            seq = list(range(start, end, step))
    except (ValueError, TypeError):
        seq = []
    return seq


@register.filter
def epoch(value):
    try:
        return int(time.mktime(value.timetuple())*1000)
    except AttributeError:
        return ''

@register.filter
def to_int(value):
    return int(value)


@register.simple_tag
def math_inc(value):
    return value + 1


@register.simple_tag
def math_dec(value):
    return value - 1

@register.simple_tag
def math_sub(value, arg):
    return value - arg

@register.simple_tag
def math_add(value, arg):
    return value + arg

@register.simple_tag
def math_mul(value, arg):
    return value * arg

@register.simple_tag
def math_div(value, arg):
    return value / arg

@register.simple_tag
def define(val=None):
    return val

@register.simple_tag
def concat(*args):
    c = ""
    for arg in args:
        c += str(arg)
    return c

@register.filter
def nope(value):
    try:
        return not int(value)
    except:
        return False

@register.simple_tag
def dict_to_json(dictionary):
    return json.dumps(dictionary)


@register.simple_tag
def from_dict(dictionary, key):
    return dictionary.get(key)

@register.simple_tag
def from_list(lst, key):
    try:
        return lst[key]
    except:
        return ""

@register.simple_tag
def from_choices(dictionary, key):
    for k, v in dictionary:
        if k == key:
            return v
    return ''

@register.simple_tag
def in_intlist(lst, key):
    return key in lst

@register.simple_tag
def in_charlist(lst, key):
    return str(key) in lst

