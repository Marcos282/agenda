from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from .domains import tenant_base_domain_for_host
from .models import Tenant


def resolve_tenant(host):
    # get_host() has already validated ALLOWED_HOSTS. No forwarded-host trust.
    from django.http.request import split_domain_port
    host, _ = split_domain_port(host.lower())
    base = tenant_base_domain_for_host(host)
    if host in {base, "localhost", "127.0.0.1", "[::1]"}:
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
        if request.tenant is not None and request.tenant.dias_para_expirar < 0:
            if request.path_info.startswith('/painel/') and request.path_info.rstrip('/') != '/painel/mensalidade':
                if user.is_authenticated:
                    if user.tipo == 'ADMIN':
                        return redirect('painel:mensalidade')
                    return HttpResponseForbidden('O painel está indisponível enquanto a mensalidade estiver vencida.')
                return redirect_to_login(reverse('painel:mensalidade'), login_url=reverse('login'))
            if request.path_info.startswith('/agendamentos/servico/'):
                return render(request, 'usuarios/agendamentos_indisponiveis.html', status=503)
        with timezone.override(ZoneInfo(request.tenant.timezone) if request.tenant else settings.TIME_ZONE):
            return self.get_response(request)
