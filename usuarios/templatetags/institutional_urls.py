from django import template

from usuarios.institutional_i18n import DEFAULT, localized_path

register = template.Library()


@register.simple_tag(takes_context=True)
def institutional_path(context, page):
    current = context.get('current_language', {})
    return localized_path(page, current.get('code', DEFAULT))
