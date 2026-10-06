from datetime import time
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from usuarios.models import WhatsAppBloqueado
from usuarios.validators import whatsapp_liberado_para_testes
from .test_booking import BookingFixture


@override_settings(WHATSAPP_TEST_RECIPIENTS='marcos:21990921092')
class TestRecipientTests(BookingFixture, TestCase):
    def setUp(self):
        self.setup_booking()
        self.user.whatsapp = '+5521990921092'
        self.user.save()
        self.tenant.limite_agendamentos_cliente_dia = 1
        self.tenant.limite_agendamentos_cliente_futuros = 1
        self.tenant.save()

    def test_only_authorized_number_bypasses_block_and_quantity_limits(self):
        WhatsAppBloqueado.objects.create(tenant=self.tenant, whatsapp=self.user.whatsapp)
        for hour in [time(9, 7), time(9, 47), time(10, 27)]:
            self.book(hour)
        self.assertEqual(self.user.agendamentos.count(), 3)

    def test_other_numbers_keep_quantity_limits_and_blocks(self):
        self.book(cliente=self.second)
        with self.assertRaises(ValidationError):
            self.book(time(9, 47), cliente=self.second)
        WhatsAppBloqueado.objects.create(tenant=self.tenant, whatsapp=self.second.whatsapp)
        with self.assertRaisesMessage(ValidationError, 'bloqueado'):
            self.book(time(10, 27), cliente=self.second)

    def test_exception_is_tenant_scoped_and_normalizes_formats(self):
        self.assertTrue(whatsapp_liberado_para_testes(self.tenant, '(21) 99092-1092'))
        self.assertTrue(whatsapp_liberado_para_testes(self.tenant, '+5521990921092'))
        self.assertFalse(whatsapp_liberado_para_testes(self.other, '+5521990921092'))
        self.assertFalse(whatsapp_liberado_para_testes(self.tenant, self.second.whatsapp))

    def test_exemption_does_not_release_occupied_times_or_cross_tenant_access(self):
        self.book()
        with self.assertRaises(ValidationError):
            self.book()
        with self.assertRaisesMessage(ValidationError, 'Cliente inválido'):
            self.book(time(9, 47), tenant=self.other)

    @override_settings(WHATSAPP_TEST_RECIPIENTS='')
    def test_empty_setting_disables_exception(self):
        self.book()
        with self.assertRaises(ValidationError):
            self.book(time(9, 47))
