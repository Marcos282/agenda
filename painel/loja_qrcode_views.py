from io import BytesIO

import qrcode
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.http import Http404
from django.urls import reverse
from profissionais.models import Profissional
from usuarios.models import User
from django.views.decorators.http import require_GET

from .decorators import admin_tenant_required


def endereco_loja(tenant, profissional=None):
    path = reverse('home_profissional', args=[profissional.pk]) if profissional else '/'
    return f'https://{tenant.subdomain}.{settings.STORE_BASE_DOMAIN}{path}'


def profissionais_qr(request):
    equipe = Profissional.objects.for_tenant(request.tenant).ativos()
    selected = request.GET.get('profissional', '')
    profissional = None
    if selected:
        if not selected.isascii() or not selected.isdecimal() or len(selected) > 18:
            raise Http404('Profissional inválido.')
        profissional = get_object_or_404(equipe, pk=int(selected))
    return equipe, profissional


def endereco_fisico(tenant):
    admin = User.objects.filter(tenant=tenant, tipo='ADMIN', is_active=True).order_by('pk').first()
    if not admin:
        return ''
    street = ', '.join(filter(None, [admin.endereco, admin.numero_endereco]))
    city = ' / '.join(filter(None, [admin.cidade, admin.estado]))
    return ' — '.join(filter(None, [street, admin.bairro, city]))


@admin_tenant_required
@require_GET
def loja_qrcode(request):
    equipe, selecionado = profissionais_qr(request)
    return render(request, 'painel/loja_qrcode.html', {
        'endereco_loja': endereco_loja(request.tenant, selecionado),
        'equipe': equipe, 'profissional_selecionado': selecionado,
        'perfil_profissional': selecionado or equipe.first(),
        'endereco_fisico': endereco_fisico(request.tenant),
    })


@admin_tenant_required
@require_GET
def loja_qrcode_imagem(request):
    _, profissional = profissionais_qr(request)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
    qr.add_data(endereco_loja(request.tenant, profissional))
    qr.make(fit=True)
    output = BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(output, format='PNG')
    response = HttpResponse(output.getvalue(), content_type='image/png')
    disposition = 'attachment' if request.GET.get('download') == '1' else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="qrcode-{request.tenant.subdomain}.png"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
