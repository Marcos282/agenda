"""Batch opening inside Agenda, using the existing daily configuration service."""
import hashlib
import json
from datetime import timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

from django import forms
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from agenda.models import Disponibilidade, Agendamento
from agenda.services import configurar_dia, revisao_dia
from profissionais.models import Profissional
from tenants.models import Tenant

SALT = 'agenda.abertura.lote.v1'


class AberturaLoteForm(forms.Form):
    data_inicial = forms.DateField(label='Data inicial', input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(format='%d/%m/%Y', attrs={'type': 'text', 'inputmode': 'numeric',
            'placeholder': 'dd/mm/aaaa', 'maxlength': 10, 'autocomplete': 'off',
            'pattern': '[0-9]{2}/[0-9]{2}/[0-9]{4}', 'data-date-br': '1'}))
    quantidade_dias = forms.IntegerField(label='Quantidade de dias', min_value=1, max_value=7, initial=7,
        widget=forms.NumberInput(attrs={'min': 1, 'max': 7}))
    profissionais = forms.ModelMultipleChoiceField(queryset=Profissional.objects.none())
    datas = forms.MultipleChoiceField()
    manha = forms.BooleanField(required=False, label='Ativar turno da manhã', initial=True)
    manha_inicio = forms.TimeField(required=False, initial='08:00', label='Início da manhã', widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}))
    manha_fim = forms.TimeField(required=False, initial='12:00', label='Fim da manhã', widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}))
    tarde = forms.BooleanField(required=False, label='Ativar turno da tarde', initial=True)
    tarde_inicio = forms.TimeField(required=False, initial='13:00', label='Início da tarde', widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}))
    tarde_fim = forms.TimeField(required=False, initial='18:00', label='Fim da tarde', widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}))
    confirmar = forms.BooleanField(required=False)
    token = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.fields['profissionais'].queryset = Profissional.objects.for_tenant(tenant).ativos()
        start = self.data.get('data_inicial') if self.is_bound else self.initial.get('data_inicial')
        count = self.data.get('quantidade_dias', 7) if self.is_bound else 7
        self.days = []
        try:
            start = forms.DateField(input_formats=['%d/%m/%Y', '%Y-%m-%d']).clean(start)
            count = forms.IntegerField(min_value=1, max_value=7).clean(count)
            self.days = [start + timedelta(days=i) for i in range(count)]
        except (ValidationError, TypeError, OverflowError):
            pass
        self.fields['datas'].choices = [(day.isoformat(), day.isoformat()) for day in self.days]

    def clean(self):
        data = super().clean()
        today = timezone.localdate(timezone=ZoneInfo(self.tenant.timezone))
        if data.get('data_inicial') and data['data_inicial'] < today:
            self.add_error('data_inicial', 'Escolha hoje ou uma data futura.')
        if not self.days and data.get('data_inicial') and data.get('quantidade_dias'):
            raise ValidationError('Período de datas inválido.')
        periods = []
        for shift in ('manha', 'tarde'):
            if data.get(shift):
                start, end = data.get(shift + '_inicio'), data.get(shift + '_fim')
                if start is None or end is None or start >= end or start.second or end.second:
                    self.add_error(shift + '_fim', 'Informe início e fim válidos, em minutos, no mesmo dia.')
                else:
                    periods.append((start, end))
        if not periods:
            raise ValidationError('Ative pelo menos um turno válido.')
        if len(periods) == 2 and periods[0][1] > periods[1][0]:
            raise ValidationError('A tarde deve começar após o fim da manhã, sem sobreposição.')
        data['periodos'] = periods
        return data

    def parameters(self):
        d = self.cleaned_data
        return {'tenant': self.tenant.pk, 'profissionais': sorted(p.pk for p in d['profissionais']),
            'datas': sorted(set(d['datas'])), 'data_inicial': d['data_inicial'].isoformat(),
            'quantidade_dias': d['quantidade_dias'],
            'periodos': [[a.isoformat(), b.isoformat()] for a, b in d['periodos']]}


def snapshot(tenant, ids, dates):
    periods = list(Disponibilidade.objects.for_tenant(tenant).filter(profissional_id__in=ids,
        data__in=dates).order_by('pk'))
    bookings = list(Agendamento.objects.for_tenant(tenant).filter(profissional_id__in=ids)
        .annotate(dia_lote=TruncDate('inicio', tzinfo=ZoneInfo(tenant.timezone)))
        .filter(dia_lote__in=dates).order_by('pk').values_list('pk', 'status', 'inicio', 'fim'))
    state = [[p.pk, p.profissional_id, p.data, p.hora_inicio, p.hora_fim, p.ativo, p.atualizado_em] for p in periods]
    digest = hashlib.sha256(json.dumps([state, bookings], default=str).encode()).hexdigest()
    return periods, digest


@transaction.atomic
def process_batch(form, *, save=False):
    params = form.parameters()
    Tenant.objects.select_for_update().get(pk=form.tenant.pk, ativo=True)
    ids = params['profissionais']
    professionals = list(Profissional.objects.for_tenant(form.tenant).ativos().select_for_update()
                         .filter(pk__in=ids).order_by('pk'))
    if len(professionals) != len(ids):
        raise ValidationError('A seleção de profissionais mudou. Confira novamente.')
    dates = [forms.DateField().clean(value) for value in params['datas']]
    periods, revision = snapshot(form.tenant, ids, dates)
    protected = set(Agendamento.objects.for_tenant(form.tenant)
        .filter(profissional_id__in=ids, status__in=['CONFIRMADO', 'NAO_COMPARECEU'], fim__gt=timezone.now())
        .annotate(dia_lote=TruncDate('inicio', tzinfo=ZoneInfo(form.tenant.timezone)))
        .filter(dia_lote__in=dates).values_list('profissional_id', 'dia_lote'))
    desired = set(form.cleaned_data['periodos'])
    changes = []
    blocked = []
    created = updated = unchanged = 0
    for professional in professionals:
        for day in dates:
            previous = [p for p in periods if p.profissional_id == professional.pk and p.data == day]
            active = sorted((p for p in previous if p.ativo), key=lambda p: (p.hora_inicio, p.pk))
            if {(p.hora_inicio, p.hora_fim) for p in active} == desired:
                unchanged += 1
                continue
            if (professional.pk, day) in protected:
                blocked.append(f'{professional.nome} · {day:%d/%m/%Y}')
            if previous:
                updated += 1
                changes.append(f'{professional.nome} · {day:%d/%m/%Y}')
            else:
                created += 1
    if blocked:
        raise ValidationError('O lote não pode alterar horários de dias com reservas futuras ou em andamento: '
            + '; '.join(blocked) + '. Desmarque essas datas ou use a configuração individual. Nenhuma agenda foi alterada.')
    summary = {'created': created, 'updated': updated, 'unchanged': unchanged,
               'changes': changes, 'professionals': len(ids), 'days': len(dates),
               'names': [p.nome for p in professionals], 'dates': [day.strftime('%d/%m/%Y') for day in dates],
               'hours': [f'{a:%H:%M} → {b:%H:%M}' for a, b in form.cleaned_data['periodos']]}
    if not save:
        return {**summary, 'token': signing.dumps({'params': params, 'revision': revision}, salt=SALT)}
    try:
        token = signing.loads(form.cleaned_data.get('token', ''), salt=SALT, max_age=900)
    except signing.BadSignature:
        raise ValidationError('Confira a prévia novamente antes de salvar.') from None
    if token.get('params') != params or token.get('revision') != revision:
        raise ValidationError('A agenda ou a seleção mudou. Confira a prévia novamente.')
    if updated and not form.cleaned_data.get('confirmar'):
        raise ValidationError('Confirme explicitamente a alteração dos horários existentes.')
    for professional in professionals:
        for day in dates:
            active = sorted((p for p in periods if p.profissional_id == professional.pk and p.data == day and p.ativo),
                            key=lambda p: (p.hora_inicio, p.pk))
            if {(p.hora_inicio, p.hora_fim) for p in active} != desired:
                configurar_dia(tenant=form.tenant, profissional_id=professional.pk, data=day,
                    periodos=form.cleaned_data['periodos'], revisao=revisao_dia(active))
    return summary


def batch_page(request):
    today = timezone.localdate(timezone=ZoneInfo(request.tenant.timezone))
    try:
        origin_day = forms.DateField(input_formats=['%Y-%m-%d']).clean(request.GET.get('data', today.isoformat()))
    except ValidationError:
        origin_day = today
    try:
        origin_pk = int(request.GET.get('profissional', ''))
        if not 0 < origin_pk <= 9223372036854775807:
            raise ValueError
    except (TypeError, ValueError):
        origin_pk = None
    origin_professional = Profissional.objects.for_tenant(request.tenant).ativos().filter(pk=origin_pk).first()
    back_params = {'data': origin_day.isoformat()}
    if origin_professional:
        back_params['profissional'] = origin_professional.pk
    back_url = reverse('painel:agenda') + '?' + urlencode(back_params)
    form = AberturaLoteForm(request.POST if request.method == 'POST' else None, tenant=request.tenant,
        initial={'data_inicial': max(today, origin_day), 'quantidade_dias': 7})
    preview = None
    success = None
    status = 200
    if request.method == 'POST':
        if form.is_valid():
            try:
                saving = request.POST.get('acao') == 'salvar_lote'
                result = process_batch(form, save=saving)
                if saving:
                    success = 'Agendas configuradas. Agendamentos existentes foram preservados.'
                    ids = [p.pk for p in form.cleaned_data['profissionais']]
                    professional_id = origin_professional.pk if origin_professional and origin_professional.pk in ids else min(ids)
                    back_url = reverse('painel:agenda') + '?' + urlencode({
                        'profissional': professional_id, 'data': min(form.cleaned_data['datas'])})
                else:
                    preview = result
                if request.headers.get('Accept') == 'application/json':
                    return JsonResponse({'ok': True, 'saved': saving, 'message': success, 'agenda_url': back_url, **result})
            except ValidationError as exc:
                form.add_error(None, exc)
                status = 409
        else:
            status = 400
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'ok': False, 'errors': form.errors.get_json_data()}, status=status)
    selected = set(request.POST.getlist('profissionais')) if form.is_bound else ({str(origin_professional.pk)} if origin_professional else set())
    professionals = [{'object': p, 'selected': str(p.pk) in selected}
        for p in form.fields['profissionais'].queryset]
    selected_dates = set(request.POST.getlist('datas')) if form.is_bound else {d.isoformat() for d in form.days}
    return render(request, 'painel/agenda/lote.html', {'form': form, 'batch_professionals': professionals,
        'batch_days': [{'day': d, 'selected': d.isoformat() in selected_dates} for d in form.days],
        'preview': preview, 'batch_success': success, 'batch_back_url': back_url}, status=status)
