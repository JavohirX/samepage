"""DRF content negotiation that never refuses.

Each view picks HTML, JSON or CSV itself (core/renderers.py: the suffix, then Accept). DRF's own
negotiation only knows the JSON renderer, so a client sending exactly `Accept: text/html` got a
406 before the view ran. This hands DRF its one renderer and leaves the choice to the view.
"""

from rest_framework.negotiation import DefaultContentNegotiation


class ViewChoosesFormat(DefaultContentNegotiation):
    """Parsers are matched as usual; the renderer choice is never a 406."""

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type
