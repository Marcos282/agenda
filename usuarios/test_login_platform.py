from django.test import TestCase, override_settings
from django.contrib.sessions.models import Session
from django.utils import timezone
from datetime import timedelta
from tenants.models import Tenant
from usuarios.models import User


@override_settings(DEBUG=True)
class PlatformLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant=Tenant.objects.create(nome='Salão',subdomain='salao')
        cls.other=Tenant.objects.create(nome='Outro',subdomain='outro')
        cls.user=User.objects.create_user('admin@example.test','Senha!9274Teste',tenant=cls.tenant,tipo='ADMIN')

    def ticket(self):
        response=self.client.post('/login/',{'email':self.user.email,'password':'Senha!9274Teste'},HTTP_HOST='localhost:8000')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('_auth_user_id',self.client.session)
        return response.context['ticket']

    def complete(self,ticket,host='salao.localhost:8000',origin='http://localhost:8000'):
        return self.client.post('/login/continuar/',{'ticket':ticket},HTTP_HOST=host,HTTP_ORIGIN=origin)

    def test_root_login_and_single_use(self):
        self.assertContains(self.client.get('/login/',HTTP_HOST='localhost'),'E-mail')
        self.assertContains(self.client.get('/',HTTP_HOST='localhost'),'href="/login/" class="ui-button ui-button-secondary">Já sou cliente')
        ticket=self.ticket()
        response=self.complete(ticket)
        self.assertEqual(response.url,'/painel/')
        self.assertEqual(self.client.get('/painel/',HTTP_HOST='salao.localhost:8000').status_code,200)
        self.assertEqual(self.complete(ticket).status_code,403)

    def test_origin_tenant_and_expiration(self):
        ticket=self.ticket()
        self.assertEqual(self.complete(ticket,origin='http://evil.example').status_code,403)
        self.assertEqual(self.complete(ticket,host='outro.localhost:8000').status_code,403)
        Session.objects.filter(session_key=ticket).update(expire_date=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.complete(ticket).status_code,403)

    def test_inactive_and_bad_password(self):
        response=self.client.post('/login/',{'email':self.user.email,'password':'incorrect'},HTTP_HOST='localhost')
        self.assertContains(response,'E-mail ou senha inválidos')
        self.tenant.ativo=False;self.tenant.save()
        response=self.client.post('/login/',{'email':self.user.email,'password':'Senha!9274Teste'},HTTP_HOST='localhost')
        self.assertContains(response,'E-mail ou senha inválidos')
