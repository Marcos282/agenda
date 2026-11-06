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

    def test_google_tag_is_loaded_once_on_public_pages_only(self):
        tag_url = 'https://www.googletagmanager.com/gtag/js?id=G-QNYYDDRTKK'
        for host, path in [
            ('localhost', '/'),
            ('marcos.localhost', '/'),
            ('marcos.localhost', f'/loja/{self.offer.pk}/'),
        ]:
            with self.subTest(host=host, path=path):
                response = self.client.get(path, HTTP_HOST=host)
                self.assertContains(response, tag_url, count=1)
                self.assertContains(response, "gtag('config', 'G-QNYYDDRTKK');", count=1)
                head = response.content.decode().split('</head>', 1)[0]
                self.assertIn(tag_url, head)
        response = self.client.get('/login/', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, tag_url)

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
        self.assertNotContains(page, 'Registre-se')

    def test_booking_button_targets_point_after_booking_note(self):
        from django.urls import reverse

        service = Servico.objects.create(tenant=self.tenant, nome='Barba')
        ProfissionalServico.objects.create(
            tenant=self.tenant, profissional=self.prof, servico=service,
            valor='20.00', duracao_minutos=20,
        )
        for path in ['/', reverse('home_profissional', args=[self.prof.pk])]:
            with self.subTest(path=path):
                page = self.client.get(path, HTTP_HOST='marcos.localhost')
                self.assertContains(page, 'agendamento online.</p><div id="fim-servicos"></div>', count=1)
                self.assertContains(page, 'class="ui-button mobile-booking-button" href="#fim-servicos"')
                self.assertNotContains(page, 'ultimo-servico')

    def test_booking_button_has_target_when_catalog_is_empty(self):
        ProfissionalServico.objects.filter(tenant=self.tenant).delete()
        page = self.get()
        self.assertContains(page, 'agendamento online.</p><div id="fim-servicos"></div>', count=1)
        self.assertContains(page, 'class="ui-button mobile-booking-button" href="#fim-servicos"')

    def test_hero_has_no_action_buttons(self):
        for path in ['/', f'/profissional/{self.prof.pk}/']:
            with self.subTest(path=path):
                page = self.client.get(path, HTTP_HOST='marcos.localhost')
                self.assertNotContains(page, 'Explorar serviços')
                self.assertNotContains(page, 'Conhecer a equipe')
                self.assertNotContains(page, 'hero-actions')
                self.assertNotContains(page, 'hero-primary')
                hero = page.content.decode().split('<section class="hero">', 1)[1].split('</section>', 1)[0]
                self.assertNotIn('<a ', hero)
                self.assertIn('<h1 class="hero-title"><span class="visually-hidden">Marcos</span></h1>', hero)
                self.assertNotIn('class="hero-logo"', hero)
                self.assertNotContains(page, '<header')
                self.assertNotContains(page, 'site-header')
                for removed in ('hero-copy', 'hero-art', 'hero-note', 'care-card', 'floating-note', 'picture'):
                    self.assertNotIn(removed, hero)

    def test_catalog_search_form_is_not_rendered(self):
        for path in ['/', f'/profissional/{self.prof.pk}/']:
            with self.subTest(path=path):
                page = self.client.get(path, HTTP_HOST='marcos.localhost')
                self.assertNotContains(page, 'Buscar serviço ou profissional')
                self.assertNotContains(page, 'class="catalog-search"')
                self.assertNotContains(page, 'id="service-search"')
                self.assertNotContains(page, 'id="professional-filter"')
                self.assertContains(page, 'class="service-grid"')
                self.assertContains(page, 'class="team-grid"')
                self.assertContains(page, 'class="service-card service-card-link"')

    def test_entire_service_card_links_to_its_booking(self):
        from django.urls import reverse

        service = Servico.objects.create(tenant=self.tenant, nome='Barba')
        other_offer = ProfissionalServico.objects.create(
            tenant=self.tenant, profissional=self.prof, servico=service,
            valor='20.00', duracao_minutos=20,
        )
        for path in ['/', reverse('home_profissional', args=[self.prof.pk])]:
            with self.subTest(path=path):
                page = self.client.get(path, HTTP_HOST='marcos.localhost')
                self.assertNotContains(page, 'Agendar horário')
                self.assertContains(page, 'class="service-card service-card-link"', count=2)
                for offer in [self.offer, other_offer]:
                    url = reverse('agenda:escolher_data', args=[offer.pk])
                    opening = f'<a class="service-card service-card-link" href="{url}" aria-label="Agendar {offer.servico.nome} com {self.prof.nome}">'
                    self.assertContains(page, opening, count=1)
                    card = page.content.decode().split(opening, 1)[1].split('</a>', 1)[0]
                    self.assertNotIn('<a ', card)
                    self.assertNotIn('<button', card)
                    self.assertIn('class="professional-avatar"', card)
                    self.assertIn(f'<h3>{offer.servico.nome}</h3>', card)
                    self.assertIn(f'{offer.duracao_minutos} min', card)
                    self.assertIn(f'<span class="professional-name">{self.prof.nome}</span><strong class="service-price">', card)
                    self.assertIn(f'</span><span class="service-duration">{offer.duracao_minutos} min</span></div>', card)
                    self.assertNotIn('class="service-meta"', card)

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
            other_prof = Profissional.objects.create(tenant=self.tenant, nome='Ana')
            ProfissionalServico.objects.create(
                tenant=self.tenant, profissional=other_prof, servico=self.offer.servico,
                valor='50.00', duracao_minutos=30,
            )
            for path in ['/', reverse('home_profissional', args=[self.prof.pk])]:
                with self.subTest(path=path):
                    page = self.client.get(path, HTTP_HOST='marcos.localhost')
                    self.assertContains(page, f'<span class="professional-avatar"><span aria-hidden="true">J</span><img src="{url}" alt="Foto de João" width="56" height="56" loading="lazy" onerror="this.hidden = true"></span>', count=1, html=True)
                    self.assertNotContains(page, 'service-icon')
                    if path == '/':
                        self.assertContains(page, '<span class="professional-avatar"><span aria-hidden="true">A</span></span>', count=1, html=True)
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
