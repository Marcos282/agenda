from uuid import uuid4

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from tenants.logo_generation import enqueue, is_enabled
from tenants.models import LogoAccount, LogoGeneration, TenantTheme

from .decorators import admin_tenant_required
from .logo_forms import LogoBriefForm


def saved_logo_url(theme):
    if not theme.logo_image:
        return ''
    return reverse('theme_image', args=['logo_image']) + f'?v={theme.updated_at.timestamp()}'


def credits_message(credits):
    return ngettext('Você possui %(count)s geração disponível.', 'Você possui %(count)s gerações disponíveis.',
                    credits) % {'count': credits}


def logo_context(tenant, theme):
    account = LogoAccount.objects.filter(tenant=tenant).first()
    jobs = LogoGeneration.objects.filter(tenant=tenant)
    context = {'logo_has_history': jobs.filter(status=LogoGeneration.Status.READY).exists()}
    if (not account or account.enabled) and is_enabled():
        credits = (account or LogoAccount.open_for(tenant)).credits
        context.update(
            logo_form=LogoBriefForm(initial={
                'name': tenant.nome, 'primary_color': theme.primary_color, 'secondary_color': '#ffffff',
                'style': 'modern', 'request_id': uuid4(),
            }),
            logo_credits_message=credits_message(credits),
            logo_credits=credits,
            logo_active_job=jobs.filter(status__in=LogoGeneration.ACTIVE).first(),
        )
    return context


def job_payload(job):
    credits = LogoAccount.objects.values_list('credits', flat=True).get(tenant_id=job.tenant_id)
    data = {
        'status': job.status,
        'status_url': reverse('painel:logo_status', args=[job.pk]),
        'credits': credits,
        'credits_message': credits_message(credits),
        'next_request_id': str(uuid4()),
    }
    if job.status == LogoGeneration.Status.READY:
        data.update(
            image_url=reverse('painel:logo_image', args=[job.pk]),
            download_url=reverse('painel:logo_download', args=[job.pk]),
            apply_url=reverse('painel:logo_apply', args=[job.pk]),
        )
    elif job.status == LogoGeneration.Status.FAILED:
        data['message'] = _('Não foi possível gerar a logomarca. Nenhum crédito foi descontado.')
    return JsonResponse(data)


@admin_tenant_required
@never_cache
@require_POST
def generate(request):
    form = LogoBriefForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors.get_json_data()}, status=400)
    brief = form.cleaned_data
    request_id = brief.pop('request_id')
    job, problem = enqueue(request.tenant, request_id, brief)
    if job:
        return job_payload(job)
    errors = {
        'disabled': (_('A geração de logomarcas está desativada.'), 403),
        'busy': (_('Já existe uma geração em andamento.'), 409),
        'no_credits': (_('Você não possui créditos para gerar outra logomarca.'), 409),
        'rate_limit': (_('Aguarde 30 segundos entre os pedidos de geração.'), 429),
    }
    message, status_code = errors[problem]
    return JsonResponse({'message': message}, status=status_code)


@admin_tenant_required
@never_cache
@require_GET
def status(request, pk):
    return job_payload(get_object_or_404(LogoGeneration, tenant=request.tenant, pk=pk))


def ready_job(request, pk):
    job = get_object_or_404(LogoGeneration, tenant=request.tenant, pk=pk, status=LogoGeneration.Status.READY)
    if not job.image or not job.image.name.startswith(f'tenants/{request.tenant.pk}/'):
        raise Http404
    return job


@admin_tenant_required
@never_cache
@require_GET
def image(request, pk, *, download=False):
    job = ready_job(request, pk)
    try:
        file = job.image.open('rb')
    except FileNotFoundError as error:
        raise Http404 from error
    response = FileResponse(file, content_type='image/webp', as_attachment=download, filename='logomarca.webp')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@admin_tenant_required
@never_cache
@require_POST
def apply(request, pk):
    job = ready_job(request, pk)
    if not job.image.storage.exists(job.image.name):
        raise Http404
    theme, _created = TenantTheme.objects.update_or_create(
        tenant=request.tenant, defaults={'logo_image': job.image.name, 'logo_image_enabled': True},
    )
    message = _('Logomarca aplicada ao seu site.')
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'message': message, 'saved_logo_url': saved_logo_url(theme)})
    messages.success(request, message)
    return redirect('painel:logo_history')


@admin_tenant_required
@never_cache
@require_GET
def history(request):
    jobs = LogoGeneration.objects.filter(tenant=request.tenant, status=LogoGeneration.Status.READY)
    page = Paginator(jobs, 12).get_page(request.GET.get('page'))
    return render(request, 'painel/logo_history.html', {'logos': page})
