from django.contrib import admin
from barbe.admin import site
from .models import Tenant

@admin.register(Tenant, site=site)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('nome', 'subdomain', 'ativo', 'timezone')
    exclude = ('intervalo_grade_minutos',)
    search_fields = ('nome', 'subdomain')
