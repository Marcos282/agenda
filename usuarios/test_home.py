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
        self.assertContains(page,'confirmação de agendamentos estarão disponíveis em breve')

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
        self.assertContains(page,'Nossa vitrine')
        self.assertContains(page,'Corte')
        self.assertNotContains(page,'Manicure exclusiva')
        self.assertEqual(self.client.get('/loja/',HTTP_HOST='localhost').status_code,404)
        detail=self.client.get(f'/loja/{self.offer.pk}/',HTTP_HOST='marcos.localhost')
        self.assertContains(detail,'40 minutos de atendimento')
        self.assertContains(detail,'Agendamentos online em breve')
        self.assertEqual(self.client.get(f'/loja/{self.offer.pk}/',HTTP_HOST='wanessa.localhost').status_code,404)
        self.offer.ativo=False;self.offer.save()
        self.assertEqual(self.client.get(f'/loja/{self.offer.pk}/',HTTP_HOST='marcos.localhost').status_code,404)

    def test_shop_filters_and_sorting(self):
        service=Servico.objects.create(tenant=self.tenant,nome='Barba')
        cheaper=ProfissionalServico.objects.create(tenant=self.tenant,profissional=self.prof,servico=service,valor='20',duracao_minutos=20)
        page=self.client.get('/loja/?ordem=menor-preco',HTTP_HOST='marcos.localhost')
        self.assertEqual(list(page.context['ofertas']),[cheaper,self.offer])
        page=self.client.get('/loja/?ordem=maior-preco',HTTP_HOST='marcos.localhost')
        self.assertEqual(list(page.context['ofertas']),[self.offer,cheaper])
        page=self.client.get('/loja/?q=Corte',HTTP_HOST='marcos.localhost')
        self.assertEqual(list(page.context['ofertas']),[self.offer])
        page=self.client.get(f'/loja/?profissional={self.foreign.pk}',HTTP_HOST='marcos.localhost')
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
