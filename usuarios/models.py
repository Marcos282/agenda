from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower, Trim
from django.core.exceptions import ValidationError
from .managers import UserManager
from tenants.base import TenantQuerySet
from .validators import normalizar_whatsapp, validate_whatsapp


class User(AbstractUser):
    class Tipo(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        CLIENTE = "CLIENTE", "Cliente"
        PROFISSIONAL = "PROFISSIONAL", "Profissional"

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, null=True, blank=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.CLIENTE)
    username = None
    email = models.EmailField(unique=True)
    # Empty values are retained for legacy accounts until the customer completes the profile.
    whatsapp = models.CharField('WhatsApp', max_length=16, blank=True, default='', validators=[validate_whatsapp])
    cpf = models.CharField('CPF', max_length=11, blank=True, default='')
    endereco = models.CharField('Endereço', max_length=200, blank=True, default='')
    bairro = models.CharField('Bairro', max_length=100, blank=True, default='')
    numero_endereco = models.CharField('Número', max_length=20, blank=True, default='')
    cidade = models.CharField('Cidade', max_length=100, blank=True, default='')
    estado = models.CharField('Estado (UF)', max_length=2, blank=True, default='')
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
        if self.whatsapp:
            self.whatsapp = normalizar_whatsapp(self.whatsapp)
        if self.is_superuser:
            if self.tenant_id or not self.is_staff or self.tipo != self.Tipo.ADMIN:
                raise ValidationError("Superusuário global exige tenant vazio, is_staff e tipo ADMIN.")
        elif not self.tenant_id:
            raise ValidationError({"tenant": "Usuário deve pertencer a um estabelecimento."})

    def save(self, *args, **kwargs):
        self.email = type(self).objects.normalize_email(self.email)
        if self.whatsapp:
            self.whatsapp = normalizar_whatsapp(self.whatsapp)
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


class ContatoCliente(models.Model):
    """Customer recorded by staff, without an authentication account."""
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    nome = models.CharField(max_length=150)
    whatsapp = models.CharField(max_length=16, validators=[validate_whatsapp])
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    objects = TenantQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('nome'), 'whatsapp', 'tenant', name='contato_nome_whatsapp_tenant_uniq'),
            models.UniqueConstraint(fields=['id', 'tenant'], name='contato_id_tenant_unique'),
        ]

    def save(self, *args, **kwargs):
        self.nome = ' '.join(self.nome.split())
        self.whatsapp = normalizar_whatsapp(self.whatsapp)
        return super().save(*args, **kwargs)


class WhatsAppBloqueado(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT)
    whatsapp = models.CharField(max_length=16, validators=[validate_whatsapp])
    objects = TenantQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'whatsapp'], name='whatsapp_bloqueado_tenant_uniq'),
        ]

    def save(self, *args, **kwargs):
        self.whatsapp = normalizar_whatsapp(self.whatsapp)
        return super().save(*args, **kwargs)
