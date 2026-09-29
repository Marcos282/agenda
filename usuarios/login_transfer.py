"""Single-use, short-lived login handoff without sharing authentication cookies."""
from django.conf import settings
from django.contrib.auth import login
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import transaction
from django.http import HttpResponseForbidden
from django.http.request import split_domain_port
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from tenants.domains import tenant_base_domain_for_host
from .models import User


def iniciar(request, user):
    ticket = SessionStore()
    ticket['login_transfer_user'] = user.pk
    ticket['login_transfer_hash'] = user.get_session_auth_hash()
    ticket.set_expiry(60)
    ticket.create()
    _, port = split_domain_port(request.get_host())
    suffix = ':' + port if port else ''
    scheme = request.scheme if settings.DEBUG else 'https'
    base_domain = tenant_base_domain_for_host(request.get_host())
    target = f'{scheme}://{user.tenant.subdomain}.{base_domain}{suffix}{reverse("login_continuar")}'
    response = render(request, 'usuarios/login_transfer.html', {'target': target, 'ticket':ticket.session_key})
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'origin'
    return response


@csrf_exempt
@require_POST
def concluir(request):
    # Cross-subdomain POST cannot use a tenant CSRF cookie before login.
    # Require the exact platform Origin instead; the initiating login POST is CSRF-protected.
    _, port = split_domain_port(request.get_host())
    suffix = ':' + port if port else ''
    origins = {f'https://{settings.TENANT_BASE_DOMAIN}{suffix}'}
    if settings.DEBUG:
        origins.update(f'http://{host}{suffix}' for host in {settings.TENANT_BASE_DOMAIN, '127.0.0.1', 'localhost'})
    if not request.tenant or request.headers.get('Origin') not in origins:
        return HttpResponseForbidden('Acesso inválido. Entre novamente pela plataforma.')
    with transaction.atomic():
        ticket = Session.objects.select_for_update().filter(session_key=request.POST.get('ticket', ''), expire_date__gt=timezone.now()).first()
        data = ticket.get_decoded() if ticket else {}
        user = User.objects.filter(pk=data.get('login_transfer_user'), tenant=request.tenant, is_active=True).first()
        if not user or not constant_time_compare(user.get_session_auth_hash(), data.get('login_transfer_hash', '')):
            return HttpResponseForbidden('Acesso inválido ou expirado. Entre novamente pela plataforma.')
        ticket.delete()
    login(request, user, backend='usuarios.backends.TenantBackend')
    response = redirect('painel:inicio' if user.tipo == User.Tipo.ADMIN else 'conta')
    response['Cache-Control'] = 'no-store'
    return response
