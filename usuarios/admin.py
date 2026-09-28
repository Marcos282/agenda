from django.contrib import admin
from barbe.admin import site
from .models import User

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
