from django.contrib import admin
from barbe.admin import site
from .models import Tenant

@admin.register(Tenant, site=site)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('nome', 'subdomain', 'plano', 'mensalidade', 'ativo', 'timezone', 'expira_em')
    readonly_fields = ('mensalidade',)
    exclude = ('intervalo_grade_minutos',)
    list_filter = ('plano', 'ativo', 'expira_em')
    search_fields = ('nome', 'subdomain')

    @admin.display(description='Mensalidade')
    def mensalidade(self, obj):
        from django.utils.formats import number_format
        from .pricing import monthly_price
        return f'R$ {number_format(monthly_price(), decimal_pos=2)} / mês'
