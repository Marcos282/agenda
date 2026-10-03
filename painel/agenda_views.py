from datetime import date, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Exists, OuterRef
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from agenda.forms import DiaForm, PeriodosFormSet
from agenda.models import Disponibilidade
from agenda.presentation import timeline_payload
from agenda.services import configurar_dia, revisao_dia
from profissionais.models import Profissional
from .decorators import admin_tenant_required


def agenda_url(profissional_id, dia):
    return reverse('painel:agenda') + '?' + urlencode({'profissional': profissional_id, 'data': dia.isoformat()})


def selected_day(request):
    today = timezone.localdate(timezone=ZoneInfo(request.tenant.timezone))
    value = request.GET.get('data', today.isoformat())
    form = DiaForm({'data': value})
    return form.cleaned_data['data'] if form.is_valid() else None


@admin_tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def agenda(request, profissional_id=None):
    dia = selected_day(request)
    if dia is None:
        return HttpResponseBadRequest('Data inválida. Use AAAA-MM-DD.')
    selected = profissional_id if profissional_id is not None else request.GET.get('profissional')
    profissionais = Profissional.objects.for_tenant(request.tenant).annotate(
        tem_periodos=Exists(Disponibilidade.objects.for_tenant(request.tenant).filter(
            profissional_id=OuterRef('pk'), data=dia, ativo=True,
        ))
    )
    if selected is not None:
        try:
            selected = int(selected)
        except (ValueError, TypeError):
            raise Http404
        profissional = get_object_or_404(profissionais, pk=selected)
    else:
        profissional = profissionais.first()
    if request.method == 'POST' and profissional is None:
        raise Http404
    periodos = list(Disponibilidade.objects.for_tenant(request.tenant).filter(
        profissional=profissional, data=dia, ativo=True,
    ).order_by('hora_inicio', 'pk')) if profissional else []
    revisao = revisao_dia(periodos)
    initial = [{'hora_inicio': p.hora_inicio, 'hora_fim': p.hora_fim} for p in periodos] or [{}]
    formset = PeriodosFormSet(request.POST if request.method == 'POST' else None, initial=None if request.method == 'POST' else initial, prefix='periodos')
    erro = None
    status = 200
    if request.method == 'POST' and formset.is_valid():
        try:
            configurar_dia(tenant=request.tenant, profissional_id=profissional.pk, data=dia,
                           periodos=formset.periodos(), revisao=request.POST.get('revisao'))
        except ValidationError as exc:
            erro = ' '.join(exc.messages)
            status = 409
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.__cause__, 'diag', None), 'constraint_name', None)
            if constraint != 'disp_sem_sobreposicao':
                raise
            erro = 'Houve uma alteração simultânea nos períodos. Recarregue a agenda e confira os horários.'
            status = 409
        else:
            messages.success(request, 'Agenda aberta. Períodos salvos.' if formset.periodos() else 'Agenda fechada para este dia.')
            return redirect(agenda_url(profissional.pk, dia))
    elif request.method == 'POST':
        status = 400
    aberta = bool(profissional and profissional.ativo and periodos)
    hoje = timezone.localdate(timezone=ZoneInfo(request.tenant.timezone))
    context = {
        'profissionais': profissionais, 'profissional': profissional,
        'dia': dia, 'data_iso': dia.isoformat(), 'hoje': hoje.isoformat(),
        'anterior': (dia - timedelta(days=1)).isoformat() if dia > date.min else None,
        'proximo': (dia + timedelta(days=1)).isoformat() if dia < date.max else None,
        'dia_passado': dia < hoje,
        'aberta': aberta, 'periodos': periodos, 'formset': formset, 'erro_agenda': erro,
        'revisao': request.POST.get('revisao', '') if request.method == 'POST' else revisao,
        'configurando': request.method == 'POST' or request.GET.get('configurar') == '1',
        'agenda_url': agenda_url(profissional.pk, dia) if profissional else reverse('painel:agenda'),
        'timeline': timeline_payload(profissional, dia, periodos if aberta else []) if profissional else None,
    }
    return render(request, 'painel/agenda/dia.html', context, status=status)
