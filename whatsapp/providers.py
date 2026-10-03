"""Replaceable transport for automatic appointment messages."""
from django.conf import settings
from django.utils.module_loading import import_string
from . import evolution


class EvolutionProvider:
    def send_text(self, tenant, number, text):
        return evolution.send_text(tenant, number, text)


def get_provider():
    provider_class = import_string(getattr(
        settings, 'WHATSAPP_PROVIDER', 'whatsapp.providers.EvolutionProvider',
    ))
    return provider_class()
