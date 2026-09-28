from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower, Trim
from django.core.exceptions import ValidationError
from .managers import UserManager


class User(AbstractUser):
    class Tipo(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        CLIENTE = "CLIENTE", "Cliente"
        PROFISSIONAL = "PROFISSIONAL", "Profissional"

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, null=True, blank=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.CLIENTE)
    username = None
    email = models.EmailField(unique=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
            models.CheckConstraint(condition=models.Q(email=Lower(Trim("email"))) & ~models.Q(email=""), name="user_email_normalized"),
            models.CheckConstraint(
                condition=(models.Q(tenant__isnull=False, is_superuser=False) | models.Q(tenant__isnull=True, is_superuser=True, is_staff=True, tipo="ADMIN")),
                name="user_tenant_or_global_superuser",
            ),
            models.CheckConstraint(condition=models.Q(tipo__in=["ADMIN", "CLIENTE", "PROFISSIONAL"]), name="user_tipo_valid"),
            models.UniqueConstraint(fields=["id", "tenant"], name="user_id_tenant_unique"),
        ]
        indexes = [models.Index(fields=["tenant", "tipo"], name="user_tenant_tipo_idx")]

    def clean(self):
        super().clean()
        self.email = type(self).objects.normalize_email(self.email)
        if self.is_superuser:
            if self.tenant_id or not self.is_staff or self.tipo != self.Tipo.ADMIN:
                raise ValidationError("Superusuário global exige tenant vazio, is_staff e tipo ADMIN.")
        elif not self.tenant_id:
            raise ValidationError({"tenant": "Usuário deve pertencer a um estabelecimento."})

    def save(self, *args, **kwargs):
        self.email = type(self).objects.normalize_email(self.email)
        return super().save(*args, **kwargs)


class Cliente(models.Model):
    """Tabela legada preservada; não há fluxos de negócio nesta etapa."""
    nome = models.CharField(max_length=150)
    telefone = models.CharField(max_length=20)
    ativo = models.BooleanField(default=True)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    def clean(self):
        super().clean()
        if self.user_id and self.tenant_id and self.user.tenant_id != self.tenant_id:
            raise ValidationError("Cliente e usuário devem pertencer ao mesmo tenant.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
