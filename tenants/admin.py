from django.contrib import admin
from barbe.admin import site
from .models import Tenant

@admin.register(Tenant, site=site)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('nome', 'subdomain', 'ativo', 'timezone', 'expira_em')
    exclude = ('intervalo_grade_minutos',)
    list_filter = ('ativo', 'expira_em')
    search_fields = ('nome', 'subdomain')
