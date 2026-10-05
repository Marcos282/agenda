from io import BytesIO

import qrcode
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .decorators import admin_tenant_required
from profissionais.models import Profissional


def endereco_loja(tenant):
    return f'https://{tenant.subdomain}.{settings.STORE_BASE_DOMAIN}/'


@admin_tenant_required
@require_GET
def loja_qrcode(request):
    public_url = endereco_loja(request.tenant)
    return render(request, 'painel/loja_qrcode.html', {
        'endereco_loja': public_url,
        'profissionais': [
            {'id': profissional.pk, 'nome': profissional.nome,
             'endereco': public_url.rstrip('/') + reverse('home_profissional', args=[profissional.pk]),
             'foto': reverse('painel:profissional_foto', args=[profissional.pk]) if profissional.foto else ''}
            for profissional in Profissional.objects.for_tenant(request.tenant).ativos()
        ],
    })


@admin_tenant_required
@require_GET
def loja_qrcode_imagem(request):
    return imagem_qrcode(request, endereco_loja(request.tenant), f'qrcode-{request.tenant.subdomain}')


@admin_tenant_required
@require_GET
def profissional_qrcode_imagem(request, profissional_id):
    profissional = get_object_or_404(
        Profissional.objects.for_tenant(request.tenant).ativos(), pk=profissional_id)
    url = endereco_loja(request.tenant).rstrip('/') + reverse('home_profissional', args=[profissional.pk])
    return imagem_qrcode(request, url, f'qrcode-{request.tenant.subdomain}-{profissional.pk}')


def imagem_qrcode(request, url, filename):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    output = BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(output, format='PNG')
    response = HttpResponse(output.getvalue(), content_type='image/png')
    disposition = 'attachment' if request.GET.get('download') == '1' else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}.png"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
