from types import SimpleNamespace

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from painel.decorators import admin_tenant_required
from .models import Configuracao, Lembrete, Confirmacao, LembreteRetorno
from .services import message_values
from . import evolution


class ConfiguracaoForm(forms.ModelForm):
    class Meta:
        model = Configuracao
        fields = ['lembretes_ativos', 'antecedencia_minutos', 'mensagem_lembrete']
        widgets = {'mensagem_lembrete': forms.Textarea(attrs={'rows': 6}), 'antecedencia_minutos': forms.NumberInput(attrs={'min': 1, 'max': 10080})}
        help_texts = {'antecedencia_minutos': '120 minutos = 2 horas. De 1 minuto a 7 dias.'}


class ConfirmacaoForm(forms.ModelForm):
    class Meta:
        model = Configuracao
        fields = ['confirmacoes_ativas', 'mensagem_confirmacao']
        widgets = {'mensagem_confirmacao': forms.Textarea(attrs={'rows': 6})}


class RetornoForm(forms.ModelForm):
    class Meta:
        model = Configuracao
        fields = ['retornos_ativos', 'mensagem_retorno']
        widgets = {'mensagem_retorno': forms.Textarea(attrs={'rows': 4})}


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
def configuracao_whatsapp(request):
    config, _ = Configuracao.objects.get_or_create(tenant=request.tenant)
    form = ConfiguracaoForm(instance=config)
    confirmacao_form = ConfirmacaoForm(instance=config)
    retorno_form = RetornoForm(instance=config)
    qr, status = '', ''
    if request.method == 'POST':
        action = request.POST.get('acao')
        if action == 'salvar_retorno':
            retorno_form = RetornoForm(request.POST, instance=config)
            if retorno_form.is_valid():
                retorno_form.save()
                messages.success(request, 'Configuração do lembrete de retorno salva.')
                return redirect('painel:whatsapp')
        elif action == 'salvar_confirmacao':
            confirmacao_form = ConfirmacaoForm(request.POST, instance=config)
            if confirmacao_form.is_valid():
                confirmacao_form.save()
                messages.success(request, 'Mensagem de boas-vindas salva.')
                return redirect('painel:whatsapp')
        elif action == 'salvar':
            form = ConfiguracaoForm(request.POST, instance=config)
            if form.is_valid():
                form.save()
                messages.success(request, 'Configurações do WhatsApp salvas.')
                return redirect('painel:whatsapp')
        elif action in {'conectar', 'verificar', 'desconectar'}:
            try:
                if action == 'conectar':
                    qr = evolution.connect(request.tenant)
                    status = 'Escaneie o QR code e depois verifique a conexão.' if qr else 'QR code ainda indisponível. Verifique a conexão ou gere novamente.'
                elif action == 'desconectar':
                    evolution.request('DELETE', '/instance/logout/' + evolution.instance(request.tenant))
                    status = 'WhatsApp desconectado.'

            except evolution.EvolutionError as exc:
                messages.error(request, str(exc))
    connection = {'label': 'Desconectado', 'kind': 'offline', 'number': ''}
    if evolution.configured():
        try:
            info = evolution.connection_info(request.tenant)
            if info['state'] == 'open':
                connection.update(label='Conectado', kind='online', number=info['number'])
                qr = ''
                status = ''
            elif info['state'] == 'connecting':
                connection.update(label='Conectando', kind='pending')
            elif info['state'] not in {'close', 'closed', 'missing'}:
                connection.update(label='Status indisponível', kind='unknown')
        except evolution.EvolutionError:
            connection.update(label='Status indisponível', kind='unknown')
    example = SimpleNamespace(tenant_id=request.tenant.pk, inicio=timezone.now(),
                              cliente_nome='Maria', servico_nome='Serviço escolhido',
                              profissional_nome='Profissional escolhido')
    return render(request, 'whatsapp/configuracao.html', {
        'retorno_form': retorno_form,
        'retornos': Paginator(LembreteRetorno.objects.filter(agendamento__tenant=request.tenant)
            .select_related('agendamento').order_by('-criado_em', '-pk'), 10
        ).get_page(request.GET.get('retornos_page')),
        'preview_values': message_values(request.tenant, example),
        'confirmacoes': Paginator(Confirmacao.objects.filter(agendamento__tenant=request.tenant)
            .select_related('agendamento').order_by('-criado_em', '-pk'), 10
        ).get_page(request.GET.get('confirmacoes_page')),
        'connection': connection, 'form': form, 'confirmacao_form': confirmacao_form, 'qr': qr, 'status': status, 'api_configurada': evolution.configured(),
        'envios': Paginator(
            Lembrete.objects.filter(agendamento__tenant=request.tenant)
            .select_related('agendamento').order_by('-criado_em', '-pk'), 10,
        ).get_page(request.GET.get('page')),
    })
