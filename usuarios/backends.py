from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class TenantBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        if request is None or not hasattr(request, "tenant") or password is None:
            return None
        User = get_user_model()
        email = User.objects.normalize_email(email or username)
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            User().set_password(password)  # Match password hashing cost for unknown accounts.
            return None
        if not user.check_password(password) or not self.user_can_authenticate(user):
            return None
        tenant = request.tenant
        if tenant is not None:
            if tenant.ativo and user.tenant_id == tenant.pk:
                return user
        elif user.is_superuser and user.is_staff and user.tenant_id is None:
            return user
        return None
