from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from barbe.admin import site
from .models import LogoAccount, LogoGeneration, LogoSettings, Tenant

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


@admin.register(LogoSettings, site=site)
class LogoSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'enabled', 'initial_credits')
    fields = ('enabled', 'initial_credits')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class LogoAccountAdminForm(forms.ModelForm):
    credit_adjustment = forms.IntegerField(
        label=_('Ajuste de créditos'), required=False,
        help_text=_('Digite um número positivo para adicionar ou negativo para remover créditos.'),
    )

    class Meta:
        model = LogoAccount
        fields = ('enabled',)

    def clean_credit_adjustment(self):
        adjustment = self.cleaned_data['credit_adjustment'] or 0
        balance = self.instance.credits + adjustment
        if not 0 <= balance <= 2_147_483_647:
            raise forms.ValidationError(_('O ajuste deixaria o saldo fora do intervalo permitido.'))
        if balance == 0 and LogoGeneration.objects.filter(
            tenant_id=self.instance.tenant_id, status__in=LogoGeneration.ACTIVE,
        ).exists():
            raise forms.ValidationError(_('Mantenha um crédito disponível até a geração em andamento terminar.'))
        return adjustment


@admin.register(LogoAccount, site=site)
class LogoAccountAdmin(admin.ModelAdmin):
    form = LogoAccountAdminForm
    list_display = ('tenant', 'enabled', 'credits')
    list_filter = ('enabled',)
    list_select_related = ('tenant',)
    search_fields = ('tenant__nome', 'tenant__subdomain')
    fields = ('tenant', 'enabled', 'credits', 'credit_adjustment')
    readonly_fields = ('tenant', 'credits')

    def save_model(self, request, obj, form, change):
        obj.credits += form.cleaned_data['credit_adjustment']
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.method == 'POST' and request.resolver_match.url_name == 'tenants_logoaccount_change':
            # Django Admin wraps the change form's POST in a transaction.
            return queryset.select_for_update(of=('self',))
        return queryset

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LogoGeneration, site=site)
class LogoGenerationAdmin(admin.ModelAdmin):
    list_display = ('id', 'tenant', 'status', 'model_name', 'error_code', 'total_tokens', 'created_at')
    list_filter = ('status', 'model_name', 'error_code')
    list_select_related = ('tenant',)
    search_fields = ('tenant__nome', 'tenant__subdomain', 'provider_request_id')
    fields = ('id', 'tenant', 'status', 'model_name', 'provider_request_id', 'usage', 'error_code',
              'created_at', 'started_at', 'finished_at')
    readonly_fields = fields

    @admin.display(description=_('Total de tokens'))
    def total_tokens(self, obj):
        return obj.usage.get('total_tokens')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
