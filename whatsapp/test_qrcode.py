import base64
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from agenda.test_booking import BookingFixture
from usuarios.models import User
from . import evolution


class QRImageTests(SimpleTestCase):
    def test_image_or_code_formats(self):
        output=BytesIO()
        Image.new('RGB',(2,2)).save(output,format='PNG')
        raw=base64.b64encode(output.getvalue()).decode()
        for response in [{'base64':raw},{'qrcode':{'base64':'data:image/png;base64,'+raw}}]:
            self.assertEqual(evolution.qr_image(response),'data:image/png;base64,'+raw)
        for response in [{'code':'pairing,qr,content'},{'qrcode':{'code':'pairing,qr,content'}}]:
            rendered=evolution.qr_image(response)
            image=Image.open(BytesIO(base64.b64decode(rendered.split(',',1)[1])))
            self.assertEqual(image.format,'PNG')
        self.assertEqual(evolution.qr_image({'count':0}),'')
        self.assertEqual(evolution.qr_image({'base64':'not an image'}),'')

    @patch('whatsapp.evolution.state',return_value='missing')
    @patch('whatsapp.evolution.request')
    def test_creation_without_qr_fetches_connect_endpoint(self, request, state):
        from types import SimpleNamespace
        tenant=SimpleNamespace(pk=12)
        request.side_effect=[{'instance':{'status':'created'}},{'code':'pairing,qr,content'}]
        self.assertTrue(evolution.connect(tenant).startswith('data:image/png;base64,'))
        self.assertEqual(request.call_args.args,('GET','/instance/connect/'+evolution.instance(tenant)))

    @patch('whatsapp.evolution.state',return_value='open')
    @patch('whatsapp.evolution.request')
    def test_connected_instance_does_not_reconnect(self, request, state):
        self.assertEqual(evolution.connect(object()),'')
        request.assert_not_called()


@override_settings(TENANT_BASE_DOMAIN='localhost')
class QRPanelTests(BookingFixture,TestCase):
    def setUp(self):
        self.setup_booking()
        self.admin=User.objects.create_user('qr-admin@example.test',tenant=self.tenant,tipo='ADMIN')
        self.client.force_login(self.admin)

    @patch('whatsapp.evolution.configured',return_value=True)
    @patch('whatsapp.evolution.connection_info',return_value={'state':'connecting','number':''})
    @patch('whatsapp.evolution.fetch_qrcode',return_value='data:image/png;base64,test')
    def test_verify_displays_qr_again(self, qr, info, configured):
        response=self.client.post(reverse('painel:whatsapp'),{'acao':'verificar'},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.context['qr'],'data:image/png;base64,test')
        self.assertContains(response,'QR code para conectar')
        qr.assert_called_once_with(self.tenant)

    @patch('whatsapp.evolution.configured',return_value=True)
    @patch('whatsapp.evolution.connection_info',return_value={'state':'open','number':'+5511999991234'})
    @patch('whatsapp.evolution.fetch_qrcode')
    def test_verified_connection_hides_qr(self, qr, info, configured):
        response=self.client.post(reverse('painel:whatsapp'),{'acao':'verificar'},HTTP_HOST='marcos.localhost')
        self.assertEqual(response.context['qr'],'')
        qr.assert_not_called()
