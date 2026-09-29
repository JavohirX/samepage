"""Tags for the page shell: an event tab that knows it is the current page."""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def tab(context, event_id, suffix, label):
    """A link to /e/<event_id>/<suffix> that carries aria-current="page" when it is the page shown."""
    href = f"/e/{event_id}/{suffix}" if suffix else f"/e/{event_id}"
    request = context.get("request")
    if request is not None and request.path == href:
        return format_html('<a href="{}" aria-current="page">{}</a>', href, label)
    return format_html('<a href="{}">{}</a>', href, label)
