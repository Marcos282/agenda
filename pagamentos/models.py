from uuid import uuid4

from django.db import models


class CheckoutAcesso(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.PROTECT, related_name='checkouts_acesso')
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    dias = models.PositiveSmallIntegerField(default=30)
    producao = models.BooleanField(default=False)
    preferencia_id = models.CharField(max_length=200, blank=True)
    recebedor_id = models.CharField(max_length=100, blank=True)
    checkout_url = models.URLField(max_length=1000, blank=True)
    retorno_url = models.URLField(max_length=1000)
    criado_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField()

    class Meta:
        ordering = ['-criado_em']
        constraints = [
            models.CheckConstraint(condition=models.Q(valor__gt=0), name='checkout_acesso_valor_positivo'),
            models.CheckConstraint(condition=models.Q(dias=30), name='checkout_acesso_trinta_dias'),
        ]


class PagamentoAcesso(models.Model):
    payment_id = models.CharField(max_length=100, primary_key=True)
    checkout = models.ForeignKey(CheckoutAcesso, on_delete=models.PROTECT, related_name='pagamentos')
    status = models.CharField(max_length=40)
    creditado_em = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-atualizado_em']


class NotificacaoMercadoPago(models.Model):
    class Estado(models.TextChoices):
        RECEBIDA = 'recebida', 'Recebida'
        PROCESSADA = 'processada', 'Processada'
        AGUARDANDO_REENVIO = 'aguardando_reenvio', 'Aguardando reenvio'
        SEM_CORRESPONDENCIA = 'sem_correspondencia', 'Sem correspondência'
        IGNORADA = 'ignorada', 'Ignorada'

    pagamento = models.ForeignKey(
        PagamentoAcesso, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='notificacoes_mercado_pago',
    )
    payment_id = models.CharField(max_length=100, db_index=True)
    tipo = models.CharField(max_length=80, blank=True)
    evento = models.CharField(max_length=100, blank=True)
    request_id = models.CharField(max_length=200, blank=True)
    estado = models.CharField(max_length=24, choices=Estado.choices, default=Estado.RECEBIDA)
    dado_bruto = models.TextField()
    recebido_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recebido_em']
