from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import Http404, HttpResponseForbidden
from django.utils import timezone
from .models import Tenant


def resolve_tenant(host):
    # get_host() has already validated ALLOWED_HOSTS. No forwarded-host trust.
    from django.http.request import split_domain_port
    host, _ = split_domain_port(host.lower())
    base = settings.TENANT_BASE_DOMAIN
    if host in {base, "127.0.0.1", "[::1]"}:
        return None
    suffix = "." + base
    if not host.endswith(suffix):
        raise Http404("Estabelecimento não encontrado.")
    subdomain = host[:-len(suffix)]
    if not subdomain or "." in subdomain:
        raise Http404("Estabelecimento não encontrado.")
    try:
        return Tenant.objects.get(subdomain=subdomain, ativo=True)
    except Tenant.DoesNotExist:
        raise Http404("Estabelecimento não encontrado.")


class TenantMiddleware:
    """Fail closed for every authenticated request, including public views."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = resolve_tenant(request.get_host())
        if request.tenant is not None and request.path_info.startswith("/admin/"):
            raise Http404
        user = request.user
        if user.is_authenticated:
            if request.tenant is not None:
                if user.tenant_id != request.tenant.pk:
                    return HttpResponseForbidden("Acesso negado a este estabelecimento.")
            elif not (user.is_superuser and user.tenant_id is None):
                return HttpResponseForbidden("Acesse o subdomínio do seu estabelecimento.")
        with timezone.override(ZoneInfo(request.tenant.timezone) if request.tenant else settings.TIME_ZONE):
            return self.get_response(request)
