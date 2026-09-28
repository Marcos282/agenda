"""Staff reservations with customer name and WhatsApp."""
from zoneinfo import ZoneInfo

from django import forms
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from agenda.booking import horarios_disponiveis, reservar_pelo_painel
from catalogo.models import ProfissionalServico
from usuarios.forms import WhatsAppField
from .agenda_views import agenda_url
from .decorators import admin_tenant_required


class OfertaChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        price = format(obj.valor, '.2f').replace('.', ',')
        return f'{obj.profissional.nome} · {obj.servico.nome} · {obj.duracao_minutos} min · R$ {price}'


class AgendamentoPainelForm(forms.Form):
    nome = forms.CharField(label='Cliente', max_length=150, widget=forms.TextInput(attrs={'placeholder': 'Nome completo do cliente', 'autocomplete': 'name'}))
    whatsapp = WhatsAppField()
    oferta = OfertaChoice(label='Profissional e serviço', queryset=ProfissionalServico.objects.none(), empty_label='Selecione o profissional e o serviço')
    data = forms.DateField(label='Data do atendimento', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['oferta'].queryset = ProfissionalServico.objects.for_tenant(tenant).disponiveis().select_related('profissional', 'servico', 'tenant').order_by('profissional__nome', 'servico__nome')


class HorarioPainelForm(forms.Form):
    hora = forms.TimeField(label='Horário', input_formats=['%H:%M'])
    cotacao = forms.CharField(widget=forms.HiddenInput)


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
def novo(request):
    hoje = timezone.localdate(timezone=ZoneInfo(request.tenant.timezone))
    initial = {'data': hoje}
    # Preserve the professional/day when entering from the daily agenda.
    if request.method == 'GET':
        initial['data'] = request.GET.get('data', hoje)
    form = AgendamentoPainelForm(request.POST if request.method == 'POST' else None, tenant=request.tenant, initial=initial)
    profissional_id = request.GET.get('profissional', '')
    if profissional_id.isdecimal() and len(profissional_id) <= 18 and request.method == 'GET':
        offer = form.fields['oferta'].queryset.filter(profissional_id=int(profissional_id)).first()
        if offer:
            form.initial['oferta'] = offer.pk
    context = {'form': form, 'selecionando': True}
    status = 200
    if request.method == 'POST' and form.is_valid() and request.POST.get('acao') != 'editar':
        values = form.cleaned_data
        oferta = values['oferta']
        nome = values['nome']
        quote = signing.dumps({'oferta': oferta.pk, 'valor': str(oferta.valor), 'duracao': oferta.duracao_minutos}, salt='agendamento-painel')
        horario_form = HorarioPainelForm(request.POST if request.POST.get('acao') == 'confirmar' else None, initial={'cotacao': quote})
        if request.POST.get('acao') == 'confirmar':
            status = 400
            if horario_form.is_valid():
                try:
                    quoted = signing.loads(horario_form.cleaned_data['cotacao'], salt='agendamento-painel', max_age=86400)
                    if quoted['oferta'] != oferta.pk:
                        raise signing.BadSignature
                    booking = reservar_pelo_painel(tenant=request.tenant, administrador=request.user, whatsapp=values['whatsapp'], oferta_id=oferta.pk,
                        dia=values['data'], hora=horario_form.cleaned_data['hora'], nome=nome,
                        valor_exibido=quoted['valor'], duracao_exibida=quoted['duracao'])
                except signing.BadSignature:
                    horario_form.add_error(None, 'A seleção expirou ou foi alterada. Volte aos dados e consulte os horários novamente.')
                except ValidationError as exc:
                    horario_form.add_error(None, ' '.join(exc.messages))
                    status = 409
                except ProfissionalServico.DoesNotExist:
                    horario_form.add_error(None, 'Este serviço não está mais disponível.')
                    status = 409
                except IntegrityError as exc:
                    if getattr(getattr(exc.__cause__, 'diag', None), 'constraint_name', None) != 'ag_sem_sobreposicao':
                        raise
                    horario_form.add_error(None, 'Esse horário acabou de ser reservado. Escolha outro horário.')
                    status = 409
                else:
                    messages.success(request, f'Agendamento #{booking.pk} confirmado para {nome}.')
                    return redirect(agenda_url(oferta.profissional_id, values['data']))
        context.update(selecionando=False, oferta=oferta, whatsapp=values['whatsapp'], nome=nome, dia=values['data'],
            horarios=horarios_disponiveis(oferta, values['data']), horario_form=horario_form)
    elif request.method == 'POST' and form.errors:
        status = 400
    return render(request, 'painel/agendamento_novo.html', context, status=status)


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
def cancelar_agendamento(request, pk):
    from django.http import Http404
    from django.shortcuts import get_object_or_404
    from agenda.models import Agendamento
    from agenda.booking import cancelar_pelo_painel
    if pk > 9223372036854775807:
        raise Http404
    booking = get_object_or_404(Agendamento.objects.for_tenant(request.tenant).select_related('cliente', 'contato'), pk=pk)
    dia = timezone.localtime(booking.inicio, ZoneInfo(request.tenant.timezone)).date()
    voltar = agenda_url(booking.profissional_id, dia)
    erro = None
    if request.method == 'POST':
        try:
            cancelar_pelo_painel(tenant=request.tenant, administrador=request.user, agendamento_id=booking.pk)
        except ValidationError as exc:
            erro = ' '.join(exc.messages)
        else:
            messages.success(request, f'Agendamento #{booking.pk} cancelado. O horário foi liberado e o histórico preservado.')
            return redirect(voltar)
    return render(request, 'painel/agendamento_cancelar.html', {
        'agendamento': booking, 'voltar': voltar, 'erro': erro,
        'pode_cancelar': booking.status == 'CONFIRMADO' and booking.inicio > timezone.now(),
    }, status=409 if erro else 200)


@admin_tenant_required
@require_http_methods(['GET', 'POST'])
def falta(request, pk):
    from django.http import Http404
    from django.shortcuts import get_object_or_404
    from agenda.models import Agendamento
    from agenda.booking import registrar_falta
    if pk > 9223372036854775807:
        raise Http404
    booking = get_object_or_404(Agendamento.objects.for_tenant(request.tenant), pk=pk)
    dia = timezone.localtime(booking.inicio, ZoneInfo(request.tenant.timezone)).date()
    voltar = agenda_url(booking.profissional_id, dia)
    erro = None
    if request.method == 'POST':
        try:
            registrar_falta(tenant=request.tenant, administrador=request.user, agendamento_id=booking.pk)
        except ValidationError as exc:
            erro = ' '.join(exc.messages)
        else:
            messages.success(request, f'Agendamento #{booking.pk}: falta registrada para {booking.cliente_nome}.')
            return redirect(voltar)
    return render(request, 'painel/agendamento_falta.html', {
        'agendamento': booking, 'voltar': voltar, 'erro': erro,
        'pode_marcar': booking.status == 'CONFIRMADO' and booking.inicio <= timezone.now(),
    }, status=409 if erro else 200)
