from django.contrib import admin
from barbe.admin import site
from .models import User, Cliente, ContatoCliente, ConfiguracaoTurnstile


@admin.register(ContatoCliente, site=site)
class ContatoClienteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'whatsapp', 'tenant', 'is_active', 'date_joined')
    list_filter = ('tenant', 'is_active')
    search_fields = ('nome', 'whatsapp', 'tenant__nome', 'tenant__subdomain')
    list_select_related = ('tenant',)
    fields = ('nome', 'whatsapp', 'tenant', 'is_active', 'date_joined')
    readonly_fields = ('date_joined',)
    ordering = ('nome', 'pk')

    def get_readonly_fields(self, request, obj=None):
        return ('tenant', 'date_joined') if obj is not None else self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Cliente, site=site)
class ClienteAdmin(admin.ModelAdmin):
    """Legacy customer records retained for consultation alongside current contacts."""
    list_display = ('nome', 'telefone', 'tenant', 'ativo', 'user')
    list_filter = ('tenant', 'ativo')
    search_fields = ('nome', 'telefone', 'user__email', 'tenant__nome', 'tenant__subdomain')
    list_select_related = ('tenant', 'user')
    fields = ('nome', 'telefone', 'tenant', 'ativo', 'user')
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(User, site=site)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'tenant', 'tipo', 'is_active')
    list_filter = ('tipo', 'is_active', 'tenant')
    search_fields = ('email',)
    fields = ('email', 'whatsapp', 'tenant', 'tipo', 'is_active', 'is_staff', 'is_superuser', 'date_joined', 'last_login')
    readonly_fields = tuple(field for field in fields if field != 'tipo')

    def get_readonly_fields(self, request, obj=None):
        # Global superusers must remain ADMIN; only tenant roles are editable.
        if obj is not None and obj.is_superuser:
            return self.fields
        return self.readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return self.admin_site.has_permission(request) and (obj is None or not obj.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfiguracaoTurnstile, site=site)
class ConfiguracaoTurnstileAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'turnstile_ativo', 'atualizado_em', 'atualizado_por')
    fields = ('turnstile_ativo', 'atualizado_em', 'atualizado_por')
    readonly_fields = ('atualizado_em', 'atualizado_por')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.atualizado_por = request.user
        super().save_model(request, obj, form, change)
        if not obj.turnstile_ativo:
            self.message_user(
                request,
                'Cloudflare Turnstile desativado: login, cadastro e agendamentos estão sem CAPTCHA.',
                level='WARNING',
            )

    def change_view(self, request, object_id, form_url='', extra_context=None):
        if ConfiguracaoTurnstile.objects.filter(pk=1, turnstile_ativo=False).exists():
            self.message_user(request, 'Cloudflare Turnstile está desativado globalmente.', level='WARNING')
        return super().change_view(request, object_id, form_url, extra_context)
