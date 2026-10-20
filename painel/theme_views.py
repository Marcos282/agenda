from copy import copy
from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from tenants.models import TenantTheme
from tenants.themes import gallery, PALETTE, SUGGESTIONS
from tenants.decorators import tenant_required
from .decorators import admin_tenant_required
from .theme_forms import AppearanceForm, ContentForm


def current_theme(request):
    return TenantTheme.objects.filter(tenant=request.tenant).first() or TenantTheme(tenant=request.tenant)


@admin_tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def appearance(request):
    theme = current_theme(request)
    form = AppearanceForm(request.POST or None, instance=theme)
    if request.method == 'POST' and form.is_valid():
        # ModelForm only exposes the two authorized visual fields.
        with transaction.atomic():
            TenantTheme.objects.update_or_create(tenant=request.tenant, defaults=form.cleaned_data)
        messages.success(request, 'Tema e cor aplicados ao seu site.')
        return redirect('painel:estilo')
    return render(request, 'painel/estilo.html', {'theme': theme, 'form': form, 'themes': gallery(), 'palette': PALETTE})


@admin_tenant_required
@never_cache
@require_http_methods(['GET', 'POST'])
def content(request):
    theme = current_theme(request)
    form = ContentForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=theme)
    if request.method == 'POST' and form.is_valid():
        # Only content fields are updated; concurrent appearance edits are preserved.
        with transaction.atomic():
            TenantTheme.objects.update_or_create(tenant=request.tenant, defaults=form.cleaned_data)
        messages.success(request, 'Conteúdo visual salvo.')
        return redirect('painel:estilo_conteudo')
    return render(request, 'painel/estilo_conteudo.html', {'form': form, 'suggestions': SUGGESTIONS})


@admin_tenant_required
@never_cache
@require_http_methods(['POST'])
def preview(request):
    from usuarios.views import home
    theme = current_theme(request)
    if request.POST.get('preview_kind') == 'content':
        form = ContentForm(request.POST, request.FILES or None, instance=theme)
    else:
        form = AppearanceForm(request.POST, instance=theme)
    if not form.is_valid():
        return HttpResponseBadRequest(form.errors.as_json(), content_type='application/json')
    isolated = copy(request)
    isolated.method = 'GET'
    isolated.GET = request.GET.copy()
    isolated.GET.clear()
    isolated._theme_preview = form.save(commit=False)
    response = home(isolated)
    response['Content-Security-Policy'] = "script-src 'none'; form-action 'none'; frame-ancestors 'self'; base-uri 'none'"
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@admin_tenant_required
@require_http_methods(['POST'])
def restore(request):
    if request.POST.get('confirm') != 'yes':
        return HttpResponseBadRequest('Confirme a restauração da aparência original.')
    # File references are cleared, files themselves are retained for recovery.
    defaults = {'style': 'original', 'primary_color': '#287454', 'title': '', 'subtitle': '',
                'description': '', 'button_text': '', 'icon': '', 'hero_image': '', 'background_image': ''}
    TenantTheme.objects.filter(tenant=request.tenant).update(**defaults)
    messages.success(request, 'Aparência original restaurada. Os arquivos de imagem foram preservados.')
    return redirect('painel:estilo')


@tenant_required
@require_http_methods(['GET'])
def image(request, field):
    if field not in {'hero_image', 'background_image'}:
        raise Http404
    theme = TenantTheme.objects.filter(tenant=request.tenant).first()
    file = getattr(theme, field, None)
    if not file or not file.name.startswith(f'tenants/{request.tenant.pk}/'):
        raise Http404
    try:
        response = FileResponse(file.open('rb'), content_type='image/webp')
    except FileNotFoundError:
        raise Http404
    response['Cache-Control'] = 'private, max-age=300'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
