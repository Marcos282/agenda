"""Administrative test console; no registration or instance creation."""
import logging
import time
from secrets import compare_digest, token_hex
from django.conf import settings
from django.core.cache import cache
from django import forms
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from painel.decorators import admin_tenant_required
from usuarios.validators import normalizar_whatsapp
from .providers import get_provider
from . import evolution, inbox
from .inbox_views import webhook_url

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
    return console(request, route='testezap')


def console(request, *, route, protected=False):
    if protected and request.GET.get('diagnostico') == '1':
        return JsonResponse(diagnose(request.tenant))
    if request.GET.get('mensagens') == '1' and request.method == 'GET':
        try:
            number = normalizar_whatsapp(request.GET.get('whatsapp', ''))
        except forms.ValidationError:
            return JsonResponse({'error': 'Informe um WhatsApp válido.'}, status=400)
        try:
            local_messages = inbox.messages_for(request.tenant.pk, number)
            warning = ''
            try:
                remote_messages = evolution.find_messages(request.tenant, number)
            except evolution.EvolutionError as exc:
                remote_messages = []
                warning = str(exc)
            conversation = local_messages + [message for message in remote_messages
                if not any(local['text'] == message['text'] and not message['sent'] for local in local_messages)]
            run = current_test(request)
            if run and run['number'] == number and run['status'] == 'aguardando_resposta':
                if any(not item['sent'] and run['token'] in item['text'] for item in conversation):
                    run['status'] = 'confirmado'
                    run['received_at'] = time.time()
                    request.session['whatsapp_roundtrip'] = run
            return JsonResponse({'messages': conversation,
                                 'test': run if run and run['number'] == number else None, 'warning': warning})
        except evolution.EvolutionError as exc:
            return JsonResponse({'error': str(exc)}, status=502)
    form = TestMessageForm(request.POST if request.method == 'POST' else None,
                           initial={'whatsapp': request.session.get('testezap_number', ''),
                                    'mensagem': 'Olá! Esta é uma mensagem de teste do Tá Combinado. 😊'})
    if request.method == 'POST' and form.is_valid():
        run = None
        text = form.cleaned_data['mensagem']
        if protected and request.POST.get('acao') == 'teste_completo':
            token = 'TESTE-' + token_hex(4).upper()
            text += f'\n\nPara confirmar o envio e o recebimento, responda com: {token}'
            run = {'tenant': request.tenant.pk, 'number': form.cleaned_data['whatsapp'],
                   'token': token, 'status': 'iniciado', 'started_at': time.time()}
        try:
            result = get_provider().send_text(request.tenant, form.cleaned_data['whatsapp'], text)
        except Exception as exc:
            logger.error('Falha testezap tenant=%s tipo=%s', request.tenant.pk, type(exc).__name__)
            detail = str(exc) if isinstance(exc, evolution.EvolutionError) else 'Falha inesperada no envio. Consulte o log do servidor.'
            messages.error(request, detail)
            if run:
                run.update(status='falha', error=detail)
                request.session['whatsapp_roundtrip'] = run
        else:
            if run:
                run.update(status='aguardando_resposta',
                           message_id=str(result.get('message_id', '')) if isinstance(result, dict) else '')
                request.session['whatsapp_roundtrip'] = run
            request.session['testezap_number'] = form.cleaned_data['whatsapp']
            messages.success(request, 'Mensagem aceita pela API. Confira o recebimento no celular.')
            return redirect(route)
    return render(request, 'whatsapp/testezap.html', {'form': form, 'protected': protected, 'test_run': current_test(request) if protected else None, 'webhook_url': webhook_url(request)})


class PinForm(forms.Form):
    pin = forms.CharField(label='PIN de acesso', max_length=32,
                         widget=forms.PasswordInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}))


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
def testes(request):
    now = time.time()
    tenant_id = request.tenant.pk
    key = f'whatsapp-testes-pin:{tenant_id}:{request.user.pk}'
    access = request.session.get('whatsapp_testes_access', {})
    unlocked = access.get('tenant') == tenant_id and access.get('expires', 0) > now
    if request.method == 'POST' and request.POST.get('acao') == 'bloquear':
        request.session.pop('whatsapp_testes_access', None)
        return redirect('testes')
    if unlocked:
        return console(request, route='testes', protected=True)
    if request.GET.get('mensagens') == '1' or request.GET.get('diagnostico') == '1':
        return JsonResponse({'error': 'Acesso expirado. Abra /testes e informe o PIN novamente.'}, status=403)
    form = PinForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        attempts = cache.get(key, 0)
        if attempts >= 5:
            form.add_error('pin', 'Muitas tentativas. Aguarde 10 minutos e tente novamente.')
        elif compare_digest(form.cleaned_data['pin'].encode(), str(settings.WHATSAPP_TESTS_PIN).encode()):
            cache.delete(key)
            request.session['whatsapp_testes_access'] = {'tenant': tenant_id, 'expires': now + 1800}
            return redirect('testes')
        else:
            cache.set(key, attempts + 1, 600)
            form.add_error('pin', 'PIN incorreto.')
    return render(request, 'whatsapp/testes_pin.html', {'form': form})


def diagnose(tenant):
    result = {'configured': evolution.configured(), 'instance': '',
              'status': 'indisponível', 'error': ''}
    if not result['configured']:
        result['error'] = 'A URL ou a chave da Evolution não está configurada.'
        return result
    try:
        result['instance'] = evolution.instance(tenant)
        info = evolution.connection_info(tenant)
        result.update(status=info['state'], number=info['number'])
        result['detail'] = {
            'open': 'WhatsApp conectado. Você pode testar o envio.',
            'missing': 'A instância deste estabelecimento não foi encontrada. Confira o prefixo configurado.',
            'connecting': 'A instância ainda está conectando.',
            'close': 'WhatsApp desconectado. Reconecte no painel WhatsApp.',
            'closed': 'WhatsApp desconectado. Reconecte no painel WhatsApp.',
        }.get(info['state'], 'A Evolution respondeu com estado desconhecido.')
    except evolution.EvolutionError as exc:
        result['error'] = str(exc)
    return result


def current_test(request):
    run = request.session.get('whatsapp_roundtrip')
    return run if run and run.get('tenant') == request.tenant.pk else None
