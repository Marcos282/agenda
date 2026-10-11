from concurrent.futures import ThreadPoolExecutor
from datetime import date, time, timedelta
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from threading import Barrier

from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError, close_old_connections, connection, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from agenda.models import Disponibilidade
from catalogo.models import Servico, ProfissionalServico
from painel.forms import ProfissionalForm
from profissionais.models import Profissional
from tenants.models import Tenant
from usuarios.models import User

PASSWORD = 'Senha!Painel_2026'
DAY = timezone.localdate() + timedelta(days=1)


class PanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marcos = Tenant.objects.create(nome='Marcos', subdomain='marcos', plano=Tenant.Plano.PROFISSIONAL)
        cls.wanessa = Tenant.objects.create(nome='Wanessa', subdomain='wanessa')
        cls.admin = User.objects.create_user('admin@marcos.test', PASSWORD, tenant=cls.marcos, tipo='ADMIN')
        cls.outro_admin = User.objects.create_user('admin@wanessa.test', PASSWORD, tenant=cls.wanessa, tipo='ADMIN')
        cls.joao = Profissional.objects.create(tenant=cls.marcos, nome='João')
        cls.sandro = Profissional.objects.create(tenant=cls.marcos, nome='Sandro')
        cls.maria = Profissional.objects.create(tenant=cls.wanessa, nome='Maria')
        cls.corte = Servico.objects.create(tenant=cls.marcos, nome='Corte')
        cls.manicure = Servico.objects.create(tenant=cls.wanessa, nome='Manicure')

    def setUp(self):
        self.client.force_login(self.admin)

    def get(self, url, host='marcos.localhost'):
        return self.client.get(url, HTTP_HOST=host)

    def post(self, url, data, host='marcos.localhost'):
        return self.client.post(url, data, HTTP_HOST=host)

    def availability(self, **kwargs):
        data = dict(tenant=self.marcos, profissional=self.joao, data=DAY, hora_inicio=time(9), hora_fim=time(12))
        data.update(kwargs)
        return Disponibilidade(**data)

    def link(self, **kwargs):
        data = dict(tenant=self.marcos, profissional=self.joao, servico=self.corte, valor=Decimal('40'), duracao_minutos=30)
        data.update(kwargs)
        return ProfissionalServico(**data)

    def test_new_link_excludes_existing_services_even_inactive(self):
        offer = self.link()
        offer.save()
        url = reverse('painel:vinculo_novo', args=[self.joao.pk])
        for active in (True, False):
            offer.ativo = active
            offer.save()
            response = self.get(url)
            self.assertNotIn(self.corte, response.context['form'].fields['servico'].queryset)
            response = self.post(url, {
                'servico': self.corte.pk, 'valor': '50', 'duracao_minutos': '40', 'ativo': 'on',
            })
            self.assertContains(response, 'Volte à lista para editar ou reativar')
            self.assertNotContains(response, 'Profissional servico com este Tenant')
            self.assertEqual(ProfissionalServico.objects.filter(
                tenant=self.marcos, profissional=self.joao, servico=self.corte).count(), 1)
        other_url = reverse('painel:vinculo_novo', args=[self.sandro.pk])
        self.assertIn(self.corte, self.get(other_url).context['form'].fields['servico'].queryset)
        edit_url = reverse('painel:vinculo_editar', args=[self.joao.pk, offer.pk])
        self.assertEqual(self.post(edit_url, {
            'valor': '55', 'duracao_minutos': '45', 'ativo': 'on',
        }).status_code, 302)
        offer.refresh_from_db()
        self.assertTrue(offer.ativo)
        self.assertEqual(offer.valor, Decimal('55'))

    def test_panel_requires_admin_of_current_tenant(self):
        self.client.logout()
        self.assertEqual(self.get('/painel/').status_code, 302)
        for tipo in ['CLIENTE', 'PROFISSIONAL']:
            user = User.objects.create_user(f'{tipo}@test.com', PASSWORD, tenant=self.marcos, tipo=tipo, is_staff=True)
            self.client.force_login(user)
            expected_status = 302 if tipo == 'CLIENTE' else 403
            for path in ['/painel/', '/painel/profissionais/', '/painel/servicos/novo/', '/painel/configuracoes/']:
                self.assertEqual(self.get(path).status_code, expected_status)
                self.assertEqual(self.post(path, {}).status_code, expected_status)
        self.client.force_login(self.admin)
        self.assertEqual(self.get('/painel/').status_code, 200)
        self.assertEqual(self.get('/painel/', 'wanessa.localhost').status_code, 403)

    def test_owner_profile_page_shows_store_url_and_read_only_login(self):
        response = self.get(reverse('painel:meu_cadastro'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Meu cadastro')
        self.assertContains(response, 'https://marcos.tacombinado.net/')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'disabled')
        self.assertContains(response, 'name="first_name"')
        self.assertNotContains(response, 'name="last_name"')
        self.assertNotContains(response, 'aria-label="Painel administrativo"')
        self.assertNotContains(response, 'aria-label="Minha conta"')
        self.assertContains(self.get('/painel/'), 'Meu cadastro')
        self.assertEqual(self.get(reverse('painel:meu_cadastro'), 'wanessa.localhost').status_code, 403)

    def test_owner_profile_saves_only_owner_details_and_validates_cpf(self):
        response = self.post(reverse('painel:meu_cadastro'), {
            'first_name': 'Marcos Antonio',
            'email': 'changed@example.test',
            'cpf': '529.982.247-25',
            'telefone': '(11) 99999-1234',
            'endereco': 'Rua das Flores',
            'bairro': 'Centro',
            'numero_endereco': '123',
            'cidade': 'São Paulo',
            'estado': 'SP',
        })
        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, 'admin@marcos.test')
        self.assertEqual(self.admin.get_full_name(), 'Marcos Antonio')
        self.assertEqual(self.admin.cpf, '52998224725')
        self.marcos.refresh_from_db()
        from django.template.loader import render_to_string
        from types import SimpleNamespace
        footer = render_to_string('usuarios/footer_contact.html', {'request': SimpleNamespace(tenant=self.marcos)})
        self.assertIn('CPF 529.982.247-25', footer)
        self.assertNotIn('CNPJ', footer)
        self.assertEqual(self.admin.whatsapp, '+5511999991234')
        self.assertEqual(self.admin.endereco, 'Rua das Flores')
        self.assertEqual(self.admin.bairro, 'Centro')
        self.assertEqual(self.admin.numero_endereco, '123')
        self.assertEqual(self.admin.cidade, 'São Paulo')
        self.assertEqual(self.admin.estado, 'SP')
        self.assertEqual(self.admin.last_name, '')
        saved = self.get(reverse('painel:meu_cadastro'))
        self.assertContains(saved, 'Cadastro salvo com sucesso.')
        for field, expected in {
            'first_name': 'Marcos Antonio', 'email': 'admin@marcos.test',
            'cpf': '52998224725', 'telefone': '+5511999991234',
            'endereco': 'Rua das Flores', 'bairro': 'Centro',
            'numero_endereco': '123', 'cidade': 'São Paulo', 'estado': 'SP',
        }.items():
            self.assertEqual(saved.context['form'][field].value(), expected)

        response = self.post(reverse('painel:meu_cadastro'), {
            'first_name': 'Nome que não deve ser salvo', 'email': self.admin.email, 'cpf': '11111111111',
            'telefone': '(11) 99999-1234', 'endereco': 'Rua das Flores',
            'bairro': 'Centro', 'numero_endereco': '123', 'cidade': 'São Paulo',
            'estado': 'SP',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Informe um CPF válido.')
        self.assertContains(response, 'Não foi possível salvar.')
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.get_full_name(), 'Marcos Antonio')
        self.assertEqual(self.admin.cpf, '52998224725')

    def test_owner_profile_accepts_company_name_and_updates_public_contact(self):
        response = self.post(reverse('painel:meu_cadastro'), {
            'first_name': 'Marcos Antonio', 'cpf': 'Minha Empresa LTDA',
            'cnpj': '48992693000172',
            'telefone': '(11) 99999-1234', 'endereco': 'Rua das Flores',
            'bairro': 'Centro', 'numero_endereco': '123', 'cidade': 'São Paulo',
            'estado': 'SP',
        })
        self.assertEqual(response.status_code, 302)
        self.marcos.refresh_from_db()
        self.admin.refresh_from_db()
        self.wanessa.refresh_from_db()
        self.assertEqual(self.marcos.cnpj, '48.992.693/0001-72')
        self.assertEqual(self.marcos.endereco_publico, 'Rua das Flores, 123, Centro, São Paulo - SP')
        from django.template.loader import render_to_string
        from types import SimpleNamespace
        footer = render_to_string('usuarios/footer_contact.html', {'request': SimpleNamespace(tenant=self.marcos)})
        self.assertIn('https://wa.me/5511999991234', footer)
        self.assertIn('48.992.693/0001-72', footer)
        self.assertIn('Rua das Flores, 123, Centro, São Paulo - SP', footer)
        self.assertNotIn('tel:', footer)
        self.assertNotIn('NOVA REDE', footer)
        self.assertEqual(self.marcos.razao_social, 'Minha Empresa LTDA')
        self.assertEqual(self.marcos.telefone, '+5511999991234')
        self.assertEqual(self.admin.cpf, '')
        self.assertEqual(self.wanessa.razao_social, '')
        saved = self.get(reverse('painel:meu_cadastro'))
        self.assertEqual(saved.context['form']['cpf'].value(), 'Minha Empresa LTDA')
        self.assertContains(saved, 'CPF ou razão social')

    def test_lists_are_isolated_both_directions(self):
        for user, host, own, other, own_service, other_service in [
            (self.admin, 'marcos.localhost', 'João', 'Maria', 'Corte', 'Manicure'),
            (self.outro_admin, 'wanessa.localhost', 'Maria', 'João', 'Manicure', 'Corte'),
        ]:
            self.client.force_login(user)
            response = self.get('/painel/profissionais/', host)
            self.assertContains(response, own)
            self.assertNotContains(response, other)
            response = self.get('/painel/servicos/', host)
            self.assertContains(response, own_service)
            self.assertNotContains(response, other_service)

    def test_professional_service_registration_ignores_tenant_and_no_automatic_windows(self):
        response = self.post('/painel/profissionais/novo/', {'nome': 'Novo', 'ativo': 'on', 'tenant_id': self.wanessa.pk, 'tenant': self.wanessa.pk})
        self.assertEqual(response.status_code, 302)
        profissional = Profissional.objects.get(nome='Novo')
        self.assertEqual(profissional.tenant, self.marcos)
        self.assertFalse(profissional.disponibilidades.exists())
        self.assertFalse(profissional.servicos.exists())
        response = self.post('/painel/servicos/novo/', {'nome': 'Barba', 'ativo': 'on', 'tenant_id': self.wanessa.pk, 'valor': '99', 'duracao_minutos': 55})
        self.assertEqual(response.status_code, 302)
        servico = Servico.objects.get(nome='Barba')
        self.assertEqual(servico.tenant, self.marcos)
        self.assertFalse(hasattr(servico, 'valor'))
        self.assertFalse(hasattr(servico, 'duracao_minutos'))
        self.assertNotContains(self.get('/painel/profissionais/novo/'), 'name="tenant')

    def test_professional_edit_hides_current_photo_link_and_keeps_remove_option(self):
        profissional = Profissional.objects.create(tenant=self.marcos, nome='Com foto', foto='foto.jpg')
        form = ProfissionalForm(instance=profissional, tenant=self.marcos)

        rendered_photo_field = str(form['foto'])

        self.assertNotIn('Ver foto atual', rendered_photo_field)
        self.assertIn('Remover foto', rendered_photo_field)

    def test_professional_form_reencodes_background_photo(self):
        image = BytesIO()
        Image.new('RGBA', (20, 10), (10, 20, 30, 255)).save(image, format='PNG')
        upload = SimpleUploadedFile('fundo.png', image.getvalue(), content_type='image/png')
        form = ProfissionalForm(
            {'nome': 'Com fundo', 'ativo': 'on'}, {'foto_fundo': upload}, tenant=self.marcos)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['foto_fundo'].name, 'fundo.jpg')
        self.assertNotIn('Ver foto atual', str(form['foto_fundo']))

    def test_booking_date_page_uses_professional_background(self):
        from types import SimpleNamespace
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        profissional = Profissional.objects.create(tenant=self.marcos, nome='Com fundo', foto_fundo='fundo.jpg')
        request = RequestFactory().get('/agendamentos/servico/1/')
        request.tenant = self.marcos
        request.user = self.admin
        oferta = SimpleNamespace(pk=1, profissional=profissional, servico=SimpleNamespace(nome='Corte'),
                                 valor=Decimal('10'), duracao_minutos=30)

        rendered = render_to_string('agenda/escolher_data.html', {
            'oferta': oferta, 'horarios': [], 'dia_selecionado': date(2026, 1, 1)}, request=request)

        self.assertIn('booking-has-background', rendered)
        self.assertIn(reverse('profissional_fundo_publica', args=[profissional.pk]), rendered)

        rendered = render_to_string('agenda/horarios.html', {
            'oferta': oferta, 'horarios': [], 'dia': date(2026, 1, 1)}, request=request)

        self.assertIn('booking-has-background', rendered)
        self.assertIn(reverse('profissional_fundo_publica', args=[profissional.pk]), rendered)

    def test_professional_list_shows_profile_photos_without_view_button(self):
        profissional = Profissional.objects.create(tenant=self.marcos, nome='Com foto', foto='foto.jpg')
        from django.template.loader import render_to_string
        from django.urls import resolve
        from django.test import RequestFactory
        request = RequestFactory().get('/painel/profissionais/')
        request.tenant = self.marcos
        request.user = self.admin
        request.resolver_match = resolve(request.path)

        rendered = render_to_string(
            'painel/profissionais.html',
            {'page_obj': Profissional.objects.for_tenant(self.marcos), 'request': request},
            request=request,
        )

        self.assertIn(f'src="{reverse("painel:profissional_foto", args=[profissional.pk])}"', rendered)
        self.assertIn('alt="Foto de Com foto"', rendered)
        self.assertNotIn('Ver foto atual', rendered)

    def test_foreign_ids_rejected_on_get_and_post(self):
        foreign_link = self.link(tenant=self.wanessa, profissional=self.maria, servico=self.manicure)
        foreign_link.save()
        foreign_window = self.availability(tenant=self.wanessa, profissional=self.maria)
        foreign_window.save()
        urls = [
            reverse('painel:profissional_editar', args=[self.maria.pk]),
            reverse('painel:profissional_foto', args=[self.maria.pk]),
            reverse('painel:servico_editar', args=[self.manicure.pk]),
            reverse('painel:vinculos', args=[self.maria.pk]),
            reverse('painel:vinculo_novo', args=[self.maria.pk]),
            reverse('painel:disponibilidades', args=[self.maria.pk]),
            reverse('painel:disponibilidade_nova', args=[self.maria.pk]),
            reverse('painel:vinculo_editar', args=[self.joao.pk, foreign_link.pk]),
            reverse('painel:disponibilidade_editar', args=[self.joao.pk, foreign_window.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.get(url).status_code, 404)
                self.assertIn(self.post(url, {}).status_code, [404, 405])

    def test_parent_route_mismatch_even_inside_same_tenant_is_rejected(self):
        link = self.link(); link.save()
        window = self.availability(); window.save()
        for url in [reverse('painel:vinculo_editar', args=[self.sandro.pk, link.pk]), reverse('painel:disponibilidade_editar', args=[self.sandro.pk, window.pk])]:
            self.assertEqual(self.get(url).status_code, 404)
            self.assertEqual(self.post(url, {}).status_code, 404)

    def test_service_selection_is_scoped_and_rejects_inactive_and_foreign_ids(self):
        inactive = Servico.objects.create(tenant=self.marcos, nome='Inativo', ativo=False)
        url = reverse('painel:vinculo_novo', args=[self.joao.pk])
        response = self.get(url)
        self.assertEqual(list(response.context['form'].fields['servico'].queryset), [self.corte])
        for servico in [inactive, self.manicure]:
            response = self.post(url, {'servico': servico.pk, 'valor': '40', 'duracao_minutos': 30, 'ativo': 'on'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('servico', response.context['form'].errors)
        self.assertEqual(ProfissionalServico.objects.count(), 0)

    def test_link_prices_durations_and_tenant_are_independent(self):
        for profissional, duration, price in [(self.joao, 30, '40.00'), (self.sandro, 40, '55.00')]:
            response = self.post(reverse('painel:vinculo_novo', args=[profissional.pk]), {
                'servico': self.corte.pk, 'valor': price, 'duracao_minutos': duration, 'ativo': 'on',
                'tenant_id': self.wanessa.pk, 'profissional': self.maria.pk,
            })
            self.assertEqual(response.status_code, 302)
            link = ProfissionalServico.objects.get(profissional=profissional)
            self.assertEqual(link.tenant, self.marcos)
            self.assertEqual(link.valor, Decimal(price))
            self.assertEqual(link.duracao_minutos, duration)
        self.assertEqual(self.marcos.intervalo_grade_minutos, 15)
        url = reverse('painel:vinculo_novo', args=[self.joao.pk])
        response = self.post(url, {'servico': self.corte.pk, 'valor': '45', 'duracao_minutos': 45, 'ativo': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(ProfissionalServico.objects.count(), 2)

    def test_link_edit_and_deactivation_preserve_history_and_relationship(self):
        link = self.link(); link.save()
        response = self.post(reverse('painel:vinculo_editar', args=[self.joao.pk, link.pk]), {
            'valor': '52.50', 'duracao_minutos': 40, 'servico': self.manicure.pk, 'profissional': self.maria.pk,
        })
        self.assertEqual(response.status_code, 302)
        link.refresh_from_db()
        self.assertFalse(link.ativo)
        self.assertEqual(link.valor, Decimal('52.50'))
        self.assertEqual(link.servico, self.corte)
        self.assertEqual(link.profissional, self.joao)
        self.assertFalse(ProfissionalServico.objects.for_tenant(self.marcos).disponiveis().exists())

    def test_availability_form_and_adjacent_windows(self):
        url = reverse('painel:disponibilidade_nova', args=[self.joao.pk])
        for start, end in [('09:00', '12:00'), ('12:00', '15:00'), ('16:00', '18:00')]:
            response = self.post(url, {'data': DAY.isoformat(), 'hora_inicio': start, 'hora_fim': end, 'ativo': 'on',
                                       'tenant_id': self.wanessa.pk, 'profissional_id': self.maria.pk})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(Disponibilidade.objects.filter(tenant=self.marcos, profissional=self.joao).count(), 3)
        for start, end in [('09:00', '09:00'), ('12:00', '09:00'), ('10:00', '13:00'), ('08:00', '19:00')]:
            response = self.post(url, {'data': DAY.isoformat(), 'hora_inicio': start, 'hora_fim': end, 'ativo': 'on'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(Disponibilidade.objects.count(), 3)

    def test_availability_edit_deactivate_reactivate_conflict(self):
        window = self.availability(); window.save()
        url = reverse('painel:disponibilidade_editar', args=[self.joao.pk, window.pk])
        data = {'data': DAY.isoformat(), 'hora_inicio': '09:00', 'hora_fim': '12:00'}
        self.assertEqual(self.post(url, data).status_code, 302)
        window.refresh_from_db(); self.assertFalse(window.ativo)
        replacement = self.availability(); replacement.save()
        response = self.post(url, {**data, 'ativo': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        window.refresh_from_db(); self.assertFalse(window.ativo)
        self.assertEqual(Disponibilidade.objects.count(), 2)

    def test_inactive_parents_not_available_for_new_operations(self):
        link = self.link(); link.save()
        window = self.availability(); window.save()
        self.joao.ativo = False; self.joao.save()
        self.assertFalse(ProfissionalServico.objects.for_tenant(self.marcos).disponiveis().exists())
        self.assertFalse(Disponibilidade.objects.for_tenant(self.marcos).disponiveis().exists())
        response = self.post(reverse('painel:disponibilidade_nova', args=[self.joao.pk]), {
            'data': (DAY + timedelta(days=1)).isoformat(), 'hora_inicio': '09:00', 'hora_fim': '12:00', 'ativo': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        with self.assertRaises(ValidationError):
            self.link(servico=Servico.objects.create(tenant=self.marcos, nome='Barba')).save()
        # Still possible to close an existing period of an inactive professional.
        window.ativo = False; window.save()
        self.joao.ativo = True; self.joao.save()
        self.corte.ativo = False; self.corte.save()
        self.assertFalse(ProfissionalServico.objects.for_tenant(self.marcos).disponiveis().exists())
        link.ativo = False; link.save()

    def test_edit_professional_service_and_grid(self):
        self.assertEqual(self.post(reverse('painel:profissional_editar', args=[self.joao.pk]), {'nome': 'João editado', 'tenant': self.wanessa.pk}).status_code, 302)
        self.joao.refresh_from_db(); self.assertFalse(self.joao.ativo); self.assertEqual(self.joao.tenant, self.marcos)
        self.assertEqual(self.post(reverse('painel:servico_editar', args=[self.corte.pk]), {'nome': 'Corte editado'}).status_code, 302)
        self.corte.refresh_from_db(); self.assertFalse(self.corte.ativo)
        self.assertEqual(self.post('/painel/configuracoes/', {'intervalo_grade_minutos': 20, 'nome': 'Manipulado', 'tenant': self.wanessa.pk}).status_code, 410)
        self.marcos.refresh_from_db(); self.wanessa.refresh_from_db()
        self.assertEqual(self.marcos.intervalo_grade_minutos, 15)
        self.assertEqual(self.marcos.nome, 'Marcos')
        self.assertEqual(self.wanessa.intervalo_grade_minutos, 15)
        self.assertEqual(self.get('/painel/configuracoes/').url, reverse('painel:agenda'))

    def test_photo_upload_validation_and_tenant_protected_delivery(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            image = BytesIO(); Image.new('RGB', (20, 20), 'blue').save(image, format='PNG')
            photo = SimpleUploadedFile('original.png', image.getvalue(), content_type='image/png')
            response = self.post(reverse('painel:profissional_editar', args=[self.joao.pk]), {'nome': 'João', 'ativo': 'on', 'foto': photo})
            self.assertEqual(response.status_code, 302)
            self.joao.refresh_from_db()
            self.assertTrue(self.joao.foto.name.startswith(f'tenants/{self.marcos.pk}/'))
            photo_url = reverse('painel:profissional_foto', args=[self.joao.pk])
            response = self.get(photo_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/jpeg')
            self.assertTrue(b''.join(response.streaming_content).startswith(b'\xff\xd8'))
            self.client.force_login(self.outro_admin)
            self.assertEqual(self.get(photo_url, 'wanessa.localhost').status_code, 404)
            self.client.force_login(self.admin)
            invalid = SimpleUploadedFile('fake.jpg', b'<script>bad</script>', content_type='image/jpeg')
            response = self.post(reverse('painel:profissional_editar', args=[self.joao.pk]), {'nome': 'João', 'ativo': 'on', 'foto': invalid})
            self.assertIn('foto', response.context['form'].errors)

    def test_csrf_is_required_and_delete_is_not_exposed(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post('/painel/servicos/novo/', {'nome': 'X'}, HTTP_HOST='marcos.localhost').status_code, 403)
        url = reverse('painel:profissional_editar', args=[self.joao.pk])
        self.assertEqual(self.client.delete(url, HTTP_HOST='marcos.localhost').status_code, 405)
        self.assertTrue(Profissional.objects.filter(pk=self.joao.pk).exists())

    def test_model_relationship_validation(self):
        for obj in [self.link(servico=self.manicure), self.link(profissional=self.maria), self.availability(profissional=self.maria)]:
            with self.subTest(model=type(obj)), self.assertRaises(ValidationError):
                obj.save()

    def test_cross_tenant_foreign_keys_even_bulk_and_parent_updates(self):
        for obj in [self.link(servico=self.manicure), self.link(profissional=self.maria), self.availability(profissional=self.maria)]:
            with self.subTest(model=type(obj)), self.assertRaises(IntegrityError), transaction.atomic():
                type(obj).objects.bulk_create([obj])
        link = self.link(); link.save()
        for query in [Profissional.objects.filter(pk=self.joao.pk), Servico.objects.filter(pk=self.corte.pk)]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                query.update(tenant=self.wanessa)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProfissionalServico.objects.filter(pk=link.pk).update(tenant=self.wanessa)

    def test_database_numeric_and_required_tenant_constraints(self):
        for obj in [self.link(valor=Decimal('0')), self.link(valor=Decimal('-1')), self.link(duracao_minutos=0), Profissional(nome='Sem tenant'), Servico(nome='Sem tenant')]:
            with self.subTest(obj=type(obj)), self.assertRaises(IntegrityError), transaction.atomic():
                type(obj).objects.bulk_create([obj])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tenant.objects.filter(pk=self.marcos.pk).update(intervalo_grade_minutos=0)

    def test_database_duplicate_link_even_inactive(self):
        self.link().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProfissionalServico.objects.bulk_create([self.link(ativo=False)])

    def test_database_window_bounds_overlap_and_adjacent(self):
        self.availability().save()
        for start, end in [(9, 9), (12, 9), (10, 13), (8, 14)]:
            with self.subTest(start=start, end=end), self.assertRaises(IntegrityError), transaction.atomic():
                Disponibilidade.objects.bulk_create([self.availability(hora_inicio=time(start), hora_fim=time(end))])
        Disponibilidade.objects.bulk_create([self.availability(hora_inicio=time(12), hora_fim=time(15))])
        self.availability(profissional=self.sandro).save()
        self.availability(data=DAY + timedelta(days=1)).save()
        inactive = self.availability(ativo=False); inactive.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Disponibilidade.objects.filter(pk=inactive.pk).update(ativo=True)

    def test_history_relations_use_protect(self):
        self.link().save(); self.availability().save()
        for obj in [self.joao, self.corte, self.marcos]:
            with self.assertRaises(ProtectedError):
                obj.delete()


class ConcurrentWindowsTests(TransactionTestCase):
    def test_concurrent_overlaps_only_one_commit(self):
        tenant = Tenant.objects.create(nome='Concorrência', subdomain='concorrencia')
        professional = Profissional.objects.create(tenant=tenant, nome='João')
        barrier = Barrier(2)

        def insert_window(start, end):
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SET LOCAL statement_timeout = '10s'")
                    barrier.wait(timeout=5)
                    Disponibilidade.objects.bulk_create([Disponibilidade(
                        tenant_id=tenant.pk, profissional_id=professional.pk, data=DAY,
                        hora_inicio=time(start), hora_fim=time(end),
                    )])
                return 'created'
            except IntegrityError as exc:
                return exc.__cause__.diag.constraint_name
            except OperationalError as exc:
                # Raw simultaneous GiST inserts can resolve by aborting a deadlock victim.
                # Application writes serialize on the professional instead.
                if getattr(exc.__cause__, 'sqlstate', None) != '40P01':
                    raise
                return 'deadlock_aborted'
            finally:
                connections['default'].close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            one = executor.submit(insert_window, 9, 12)
            two = executor.submit(insert_window, 10, 13)
            results = [one.result(timeout=15), two.result(timeout=15)]
        self.assertEqual(results.count('created'), 1)
        self.assertTrue(all(result in {'created', 'disp_sem_sobreposicao', 'deadlock_aborted'} for result in results))
        self.assertEqual(Disponibilidade.objects.count(), 1)
