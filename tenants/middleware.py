from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from .domains import is_development_public_host, tenant_base_domain_for_host
from .models import Tenant


def resolve_tenant(host):
    # get_host() has already validated ALLOWED_HOSTS. No forwarded-host trust.
    from django.http.request import split_domain_port
    host, _ = split_domain_port(host.lower())
    if settings.DEBUG and host == settings.DEV_PUBLIC_HOST and settings.DEV_TENANT_SUBDOMAIN:
        try:
            return Tenant.objects.get(subdomain=settings.DEV_TENANT_SUBDOMAIN, ativo=True)
        except Tenant.DoesNotExist:
            raise Http404("Estabelecimento de teste não encontrado.")
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
        host = request.get_host()
        dev_host = is_development_public_host(host)
        user = request.user
        dev_registration = dev_host and request.path_info.rstrip('/') in {'/registro', '/registro/concluido'}
        if dev_registration or (dev_host and request.path_info.rstrip('/') == '/login' and not user.is_authenticated):
            request.tenant = None
        elif dev_host and user.is_authenticated and user.tenant_id:
            # A single tunnel has no wildcard subdomains. Scope it to the verified
            # session after login; anonymous store access keeps the configured default.
            try:
                request.tenant = Tenant.objects.get(pk=user.tenant_id, ativo=True)
            except Tenant.DoesNotExist:
                raise Http404('Estabelecimento não encontrado.')
        else:
            request.tenant = resolve_tenant(host)
        if request.tenant is not None and request.path_info.startswith("/admin/"):
            raise Http404
        if user.is_authenticated and not dev_registration:
            if request.tenant is not None:
                if user.tenant_id != request.tenant.pk:
                    return HttpResponseForbidden("Acesso negado a este estabelecimento.")
            elif request.path_info in {'/pagamentos/mercadopago/webhook/', '/pagamentos/mercadopago/sucesso/', '/pagamentos/mercadopago/pendente/', '/pagamentos/mercadopago/falha/'}:
                pass  # These endpoints authenticate signatures or redirect to a scoped tenant panel.
            elif not (user.is_superuser and user.tenant_id is None):
                return HttpResponseForbidden("Acesse o subdomínio do seu estabelecimento.")
        if request.tenant is not None and request.tenant.acesso_expirado:
            if request.path_info.startswith('/painel/') and request.path_info.rstrip('/') != '/painel/mensalidade' and not request.path_info.startswith('/painel/mensalidade/comprovantes/'):
                if user.is_authenticated:
                    if user.tipo == 'ADMIN':
                        return redirect('painel:mensalidade')
                    return HttpResponseForbidden('O painel está indisponível enquanto o prazo de acesso estiver vencido.')
                return redirect_to_login(reverse('painel:mensalidade'), login_url=reverse('login'))
            if request.path_info.startswith('/agendamentos/servico/'):
                return render(request, 'usuarios/agendamentos_indisponiveis.html', status=503)
        with timezone.override(ZoneInfo(request.tenant.timezone) if request.tenant else settings.TIME_ZONE):
            return self.get_response(request)
