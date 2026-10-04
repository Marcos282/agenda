"""Administrative test console; no registration or instance creation."""
import logging
from django import forms
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from painel.decorators import admin_tenant_required
from usuarios.validators import normalizar_whatsapp
from .providers import get_provider
from . import evolution

logger = logging.getLogger(__name__)


class TestMessageForm(forms.Form):
    whatsapp = forms.CharField(label='WhatsApp de destino', max_length=40)
    mensagem = forms.CharField(label='Mensagem', max_length=2000,
                              widget=forms.Textarea(attrs={'rows': 4}))

    def clean_whatsapp(self):
        return normalizar_whatsapp(self.cleaned_data['whatsapp'])


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
def testezap(request):
    if request.GET.get('mensagens') == '1' and request.method == 'GET':
        try:
            number = normalizar_whatsapp(request.GET.get('whatsapp', ''))
        except forms.ValidationError:
            return JsonResponse({'error': 'Informe um WhatsApp válido.'}, status=400)
        try:
            return JsonResponse({'messages': evolution.find_messages(request.tenant, number)})
        except evolution.EvolutionError as exc:
            return JsonResponse({'error': str(exc)}, status=502)
    form = TestMessageForm(request.POST if request.method == 'POST' else None,
                           initial={'whatsapp': request.session.get('testezap_number', ''),
                                    'mensagem': 'Olá! Esta é uma mensagem de teste do Tá Combinado. 😊'})
    if request.method == 'POST' and form.is_valid():
        try:
            get_provider().send_text(request.tenant, form.cleaned_data['whatsapp'], form.cleaned_data['mensagem'])
        except Exception as exc:
            logger.error('Falha testezap tenant=%s tipo=%s', request.tenant.pk, type(exc).__name__)
            messages.error(request, 'Não foi possível enviar. Confira a conexão do WhatsApp e a Evolution.')
        else:
            request.session['testezap_number'] = form.cleaned_data['whatsapp']
            messages.success(request, 'Mensagem aceita pela API. Confira o recebimento no celular.')
            return redirect('testezap')
    return render(request, 'whatsapp/testezap.html', {'form': form})
