from django.contrib import admin
from barbe.admin import site
from .models import Tenant

@admin.register(Tenant, site=site)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('nome', 'subdomain', 'ativo', 'timezone', 'expira_em')
    exclude = ('intervalo_grade_minutos',)
    readonly_fields = (
        'mercado_pago_assinatura_id', 'mercado_pago_assinatura_status',
        'mercado_pago_checkout_url', 'mercado_pago_idempotency_key',
        'mercado_pago_valor_assinatura',
    )
    list_filter = ('ativo', 'expira_em')
    search_fields = ('nome', 'subdomain')
