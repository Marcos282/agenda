from django.test import TestCase
from catalogo.models import Servico, ProfissionalServico
from profissionais.models import Profissional
from tenants.models import Tenant


class PublicHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant=Tenant.objects.create(nome='Marcos',subdomain='marcos')
        cls.other=Tenant.objects.create(nome='Wanessa',subdomain='wanessa')
        cls.prof=Profissional.objects.create(tenant=cls.tenant,nome='João',email='privado@example.com',telefone='11987654321')
        cls.foreign=Profissional.objects.create(tenant=cls.other,nome='Maria')
        service=Servico.objects.create(tenant=cls.tenant,nome='Corte')
        foreign_service=Servico.objects.create(tenant=cls.other,nome='Manicure exclusiva')
        cls.offer=ProfissionalServico.objects.create(tenant=cls.tenant,profissional=cls.prof,servico=service,valor='40.00',duracao_minutos=40)
        ProfissionalServico.objects.create(tenant=cls.other,profissional=cls.foreign,servico=foreign_service,valor='70.00',duracao_minutos=60)

    def get(self,query=''):
        return self.client.get('/'+query,HTTP_HOST='marcos.localhost')

    def test_catalog_is_dynamic_and_isolated(self):
        page=self.get()
        self.assertContains(page,'Corte')
        self.assertContains(page,'João')
        self.assertContains(page,'40,00')
        self.assertContains(page,'40 min')
        self.assertNotContains(page,'Manicure exclusiva')
        self.assertNotContains(page,'Maria')
        self.assertNotContains(page,'privado@example.com')
        self.assertNotContains(page,'11987654321')
        self.assertContains(page,'confirme seu agendamento online')

    def test_search_and_filter(self):
        self.assertEqual(list(self.get('?q=corte').context['ofertas']),[self.offer])
        self.assertEqual(list(self.get('?q=joão').context['ofertas']),[self.offer])
        for value in [str(self.foreign.pk),'bad','9'*100]:
            response = self.client.get('/?profissional='+value, HTTP_HOST='marcos.localhost', follow=True)
            self.assertEqual(response.status_code,404)
        self.assertContains(self.get('?q=ausente'),'Nenhum serviço encontrado')

    def test_inactive_records_not_publicly_offered(self):
        for obj in [self.offer,self.offer.servico,self.prof]:
            obj.ativo=False;obj.save()
            self.assertEqual(list(self.get().context['ofertas']),[])
            obj.ativo=True;obj.save()
        self.prof.ativo=False;self.prof.save()
        self.assertNotContains(self.get(),'João')

    def test_root_lookup_and_redirect_safety(self):
        root=self.client.get('/',HTTP_HOST='localhost:8000')
        self.assertContains(root,'Salões de beleza')
        self.assertNotContains(root,'Manicure exclusiva')
        self.assertContains(root,'Seus clientes recebem lembretes automáticos pelo WhatsApp antes do atendimento.')
        self.assertContains(root,'30 dias grátis')
        self.assertContains(root,'R$ 30,00 por mês.')
        self.assertContains(root,'Experimentar grátis')
        response=self.client.get('/?estabelecimento=marcos',HTTP_HOST='localhost:8000')
        self.assertEqual(response.url,'http://marcos.localhost:8000/')
        for slug in ['missing','evil.example','//evil.test','marcos@evil.test']:
            response=self.client.get('/',{'estabelecimento':slug},HTTP_HOST='localhost')
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.context['estabelecimento_form'].errors)
        self.tenant.ativo=False;self.tenant.save()
        response=self.client.get('/?estabelecimento=marcos',HTTP_HOST='localhost')
        self.assertTrue(response.context['estabelecimento_form'].errors)

    def test_catalog_pagination(self):
        for index in range(10):
            servico=Servico.objects.create(tenant=self.tenant,nome=f'Serviço {index}')
            ProfissionalServico.objects.create(tenant=self.tenant,profissional=self.prof,servico=servico,valor='10',duracao_minutos=20)
        response=self.get()
        self.assertEqual(len(response.context['ofertas']),9)
        self.assertEqual(len(self.get('?page=2').context['ofertas']),2)

    def test_shop_route_and_details_are_tenant_scoped(self):
        page=self.client.get('/loja/',HTTP_HOST='marcos.localhost')
        self.assertRedirects(page, '/inicio/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/loja/',HTTP_HOST='localhost').status_code,404)
        detail=self.client.get(f'/loja/{self.offer.pk}/',HTTP_HOST='marcos.localhost')
        self.assertContains(detail,'40 minutos de atendimento')
        self.assertContains(detail,'Horários disponíveis')
        self.assertEqual(self.client.get(f'/loja/{self.offer.pk}/',HTTP_HOST='wanessa.localhost').status_code,404)
        self.offer.ativo=False;self.offer.save()
        self.assertEqual(self.client.get(f'/loja/{self.offer.pk}/',HTTP_HOST='marcos.localhost').status_code,404)

    def test_shop_filters_and_sorting(self):
        service=Servico.objects.create(tenant=self.tenant,nome='Barba')
        cheaper=ProfissionalServico.objects.create(tenant=self.tenant,profissional=self.prof,servico=service,valor='20',duracao_minutos=20)
        page=self.client.get(f'/loja/{self.offer.pk}/?ordem=menor-preco',HTTP_HOST='marcos.localhost')
        self.assertEqual(list(page.context['ofertas']),[cheaper])
        page=self.client.get(f'/loja/{self.offer.pk}/?ordem=maior-preco',HTTP_HOST='marcos.localhost')
        self.assertEqual(list(page.context['ofertas']),[cheaper])
        page=self.client.get(f'/loja/{self.offer.pk}/?q=Corte',HTTP_HOST='marcos.localhost')
        self.assertEqual(list(page.context['ofertas']),[])
        page=self.client.get(f'/loja/{self.offer.pk}/?profissional={self.foreign.pk}',HTTP_HOST='marcos.localhost')
        self.assertEqual(list(page.context['ofertas']),[])
        self.assertEqual(self.client.post('/loja/',{},HTTP_HOST='marcos.localhost').status_code,405)

    def test_professional_route_and_legacy_redirect(self):
        path = f'/profissional/{self.prof.pk}/'
        page = self.client.get(path, HTTP_HOST='marcos.localhost')
        self.assertEqual(list(page.context['ofertas']), [self.offer])
        self.assertContains(self.get(), f'{path}#servicos')
        self.assertEqual(self.get(f'?profissional={self.prof.pk}').url, path+'#servicos')
        self.assertEqual(self.get(f'?q=&profissional={self.prof.pk}').url, path+'#servicos')
        self.assertEqual(self.get(f'?profissional={self.prof.pk}&q=corte&page=2').url, path+'?q=corte&page=2#servicos')
        self.assertEqual(self.client.get(path+'?profissional=',HTTP_HOST='marcos.localhost').url, '/#servicos')
        self.assertEqual(self.client.get(path,HTTP_HOST='wanessa.localhost').status_code,404)
        self.assertEqual(self.client.get(path,HTTP_HOST='localhost').status_code,404)
        self.prof.ativo=False;self.prof.save()
        self.assertEqual(self.client.get(path,HTTP_HOST='marcos.localhost').status_code,404)

    def test_photo_card_and_tenant_scoped_access(self):
        from tempfile import TemporaryDirectory
        from django.test import override_settings
        from django.core.files.base import ContentFile
        from django.urls import reverse
        from PIL import Image
        from io import BytesIO
        with TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            photo = BytesIO()
            Image.new('RGB', (64, 64), 'green').save(photo, 'JPEG')
            self.prof.foto.save('photo.jpg', ContentFile(photo.getvalue()))
            url = reverse('profissional_foto_publica', args=[self.prof.pk])
            self.assertContains(self.get(), 'src="'+url+'"')
            response = self.client.get(url, HTTP_HOST='marcos.localhost')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'public, max-age=300')
            page = self.client.get(reverse('home_profissional', args=[self.prof.pk]), HTTP_HOST='marcos.localhost')
            self.assertContains(page, 'property="og:image:type" content="image/jpeg"')
            self.assertContains(page, 'property="og:image:width" content="64"')
            self.assertContains(page, 'property="og:image:height" content="64"')
            self.assertIn('?v=', page.context['profile_image'])
            self.assertEqual(b''.join(response.streaming_content), photo.getvalue())
            self.assertEqual(self.client.get(url, HTTP_HOST='wanessa.localhost').status_code, 404)
            self.assertEqual(self.client.get(url, HTTP_HOST='localhost').status_code, 404)
            self.prof.ativo=False
            self.prof.save()
            self.assertEqual(self.client.get(url, HTTP_HOST='marcos.localhost').status_code, 404)
