from django.contrib.admin import AdminSite


class PlatformAdminSite(AdminSite):
    site_header = "Administração da plataforma"

    def has_permission(self, request):
        return (request.tenant is None and request.user.is_active
                and request.user.is_staff and request.user.is_superuser
                and request.user.tenant_id is None)


site = PlatformAdminSite(name='admin')
