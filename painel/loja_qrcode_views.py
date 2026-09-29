from io import BytesIO

import qrcode
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .decorators import admin_tenant_required


def endereco_loja(tenant):
    return f'https://{tenant.subdomain}.{settings.STORE_BASE_DOMAIN}/'


@admin_tenant_required
@require_GET
def loja_qrcode(request):
    return render(request, 'painel/loja_qrcode.html', {'endereco_loja': endereco_loja(request.tenant)})


@admin_tenant_required
@require_GET
def loja_qrcode_imagem(request):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
    qr.add_data(endereco_loja(request.tenant))
    qr.make(fit=True)
    output = BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(output, format='PNG')
    response = HttpResponse(output.getvalue(), content_type='image/png')
    disposition = 'attachment' if request.GET.get('download') == '1' else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="qrcode-{request.tenant.subdomain}.png"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
