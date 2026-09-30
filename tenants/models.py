from datetime import timedelta
from django.utils import timezone as django_timezone

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator
from django.db import models


subdomain_validator = RegexValidator(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    "Use um subdomínio de até 63 caracteres: letras minúsculas, números e hífens internos.",
)


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Informe um timezone IANA válido.")


class Tenant(models.Model):
    nome = models.CharField(max_length=150)
    subdomain = models.CharField(max_length=100, unique=True, validators=[subdomain_validator])
    timezone = models.CharField(max_length=50, default="America/Sao_Paulo", validators=[validate_timezone])
    # Legacy setting retained for compatibility; not used by the daily agenda.
    intervalo_grade_minutos = models.PositiveIntegerField(default=15, validators=[MinValueValidator(1)])
    ativo = models.BooleanField(default=True)
    expira_em = models.DateField('Data de expiração', null=True, blank=True,
        help_text='Validade do acesso. Quando não informada, será definida como 30 dias após o cadastro.')
    mercado_pago_assinatura_id = models.CharField(max_length=100, blank=True, default='')
    mercado_pago_assinatura_status = models.CharField(max_length=30, blank=True, default='')
    mercado_pago_checkout_url = models.URLField(max_length=500, blank=True, default='')
    mercado_pago_idempotency_key = models.UUIDField(null=True, blank=True)
    mercado_pago_valor_assinatura = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mercado_pago_diagnostico = models.JSONField(default=dict, blank=True, editable=False)
    mercado_pago_ultimo_webhook = models.JSONField(default=dict, blank=True, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(intervalo_grade_minutos__gt=0), name="tenant_grade_positiva"),
            models.CheckConstraint(condition=models.Q(subdomain__regex=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"), name="tenant_subdomain_valid"),
        ]

    @property
    def data_expiracao(self):
        if self.expira_em:
            return self.expira_em
        cadastro = self.criado_em or django_timezone.now()
        return django_timezone.localtime(cadastro, ZoneInfo(self.timezone)).date() + timedelta(days=30)

    @property
    def dias_para_expirar(self):
        hoje = django_timezone.localdate(timezone=ZoneInfo(self.timezone))
        return (self.data_expiracao - hoje).days

    def save(self, *args, **kwargs):
        validate_timezone(self.timezone)
        if self.expira_em is None:
            self.expira_em = self.data_expiracao
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'expira_em'}
        self.subdomain = self.subdomain.strip().lower()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class PlataformaPagamento(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='pagamentos_plataforma')
    mercado_pago_payment_id = models.CharField(max_length=100, unique=True)
    mercado_pago_assinatura_id = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    aprovado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
