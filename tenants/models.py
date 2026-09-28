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
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(intervalo_grade_minutos__gt=0), name="tenant_grade_positiva"),
            models.CheckConstraint(condition=models.Q(subdomain__regex=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"), name="tenant_subdomain_valid"),
        ]

    def save(self, *args, **kwargs):
        self.subdomain = self.subdomain.strip().lower()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nome
