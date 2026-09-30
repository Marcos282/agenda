from django.core.management.base import BaseCommand, CommandError
from pagamentos.services import CheckoutError, confirmar_pagamento


class Command(BaseCommand):
    help = 'Consulta um pagamento no Mercado Pago e aplica os 30 dias uma única vez.'

    def add_arguments(self, parser):
        parser.add_argument('payment_id')

    def handle(self, *args, **options):
        try:
            payment = confirmar_pagamento(options['payment_id'])
        except CheckoutError as exc:
            raise CommandError(str(exc)) from None
        if payment is None:
            raise CommandError('Pagamento não corresponde a uma compra de acesso válida.')
        self.stdout.write(f'Pagamento {payment.payment_id}: {payment.status}. '
                          f'Acesso creditado: {"sim" if payment.creditado_em else "não"}.')
