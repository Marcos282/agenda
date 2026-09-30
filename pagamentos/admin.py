from django.contrib import admin
from barbe.admin import site
from .models import CheckoutAcesso, PagamentoAcesso


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CheckoutAcesso, site=site)
class CheckoutAcessoAdmin(ReadOnlyAdmin):
    list_display = ('id', 'tenant', 'valor', 'dias', 'producao', 'criado_em')
    list_filter = ('producao',)
    search_fields = ('tenant__nome', 'tenant__subdomain', 'preferencia_id')


@admin.register(PagamentoAcesso, site=site)
class PagamentoAcessoAdmin(ReadOnlyAdmin):
    list_display = ('payment_id', 'checkout', 'status', 'creditado_em', 'atualizado_em')
    list_filter = ('status',)
    search_fields = ('payment_id', 'checkout__tenant__subdomain')
