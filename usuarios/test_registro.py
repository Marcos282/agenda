from django.test import TestCase, override_settings
from django.core import mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.urls import reverse
from tenants.models import Tenant
from usuarios.models import User


class RegistroTests(TestCase):
    def data(self, **changes):
        return dict(subdomain='meusalao', email='dono@example.test', password1='Segura!Cadastro2026', password2='Segura!Cadastro2026', **changes)

    def test_create_tenant_and_only_tenant_admin(self):
        data=self.data();data.update(tipo='CLIENTE', is_superuser='true', is_staff='true')
        response=self.client.post('/registro', data, HTTP_HOST='127.0.0.1:8000')
        self.assertRedirects(response, '/registro/concluido/', fetch_redirect_response=False)
        tenant=Tenant.objects.get(subdomain='meusalao');user=User.objects.get(email=data['email'])
        self.assertEqual(user.tenant,tenant)
        self.assertEqual(user.tipo,User.Tipo.ADMIN)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.check_password(data['password1']))
        page=self.client.get(response.url,HTTP_HOST='127.0.0.1:8000')
        self.assertContains(page,'href="/login/"')
        login=self.client.post('/login/',{'email':user.email,'password':data['password1']},HTTP_HOST='meusalao.localhost')
        self.assertEqual(login.status_code,302)
        self.assertEqual(self.client.get('/painel/',HTTP_HOST='meusalao.localhost').status_code,200)

    def test_invalid_and_duplicate_registration(self):
        for slug in ['www','foo.bar','-salao','salao-']:
            data=self.data();data['subdomain']=slug
            self.assertEqual(self.client.post('/registro',data,HTTP_HOST='localhost').status_code,200)
            self.assertFalse(Tenant.objects.exists())
        data=self.data();data['password2']='different'
        self.client.post('/registro',data,HTTP_HOST='localhost')
        self.assertFalse(Tenant.objects.exists())
        self.client.post('/registro',self.data(),HTTP_HOST='localhost')
        data=self.data();data['subdomain']='outrosalao'
        self.client.post('/registro',data,HTTP_HOST='localhost')
        self.assertEqual(Tenant.objects.count(),1)
        self.assertEqual(self.client.get('/registro',HTTP_HOST='meusalao.localhost').status_code,404)

    def test_cta_and_field_order(self):
        page=self.client.get('/',HTTP_HOST='localhost')
        self.assertContains(page,'href="/registro"')
        self.assertNotContains(page,'Conhecer a plataforma')
        page=self.client.get('/registro',HTTP_HOST='localhost')
        self.assertContains(page,'.tacombinado.net')
        self.assertLess(page.content.index(b'name="subdomain"'),page.content.index(b'name="email"'))


@override_settings(MAILERS={'default':{'BACKEND':'django.core.mail.backends.locmem.EmailBackend'}})
class RecoveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant=Tenant.objects.create(nome='Salão',subdomain='salao')
        cls.other=Tenant.objects.create(nome='Outro',subdomain='outro')
        cls.admin=User.objects.create_user('admin@example.test','Original!2026Password',tenant=cls.tenant,tipo='ADMIN')
        cls.customer=User.objects.create_user('cliente@example.test','Original!2026Password',tenant=cls.tenant)

    def test_email_scoped_and_unknown_generic(self):
        for host,email,count in [('outro.localhost',self.admin.email,0),('localhost',self.customer.email,0),('localhost','missing@example.test',0),('localhost',self.admin.email,1),('salao.localhost',self.customer.email,2)]:
            response=self.client.post('/lembrar-senha/',{'email':email},HTTP_HOST=host)
            self.assertEqual(response.status_code,302)
            self.assertEqual(len(mail.outbox),count)
        self.assertIn('/redefinir-senha/',mail.outbox[0].body)

    def test_reset_token_single_use_and_tenant_scope(self):
        token=default_token_generator.make_token(self.admin)
        uid=urlsafe_base64_encode(force_bytes(self.admin.pk))
        url=reverse('password_reset_confirm',args=[uid,token])
        response=self.client.get(url,HTTP_HOST='outro.localhost')
        self.assertContains(response,'Link inválido ou expirado')
        response=self.client.get(url,HTTP_HOST='localhost')
        clean_url=response.url
        response=self.client.post(clean_url,{'new_password1':'Nova!Senha2026Segura','new_password2':'Nova!Senha2026Segura'},HTTP_HOST='localhost')
        self.assertEqual(response.status_code,302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Nova!Senha2026Segura'))
        self.assertContains(self.client.get(url,HTTP_HOST='localhost'),'Link inválido ou expirado')

    def test_customer_reset_returns_to_customer_account(self):
        uid=urlsafe_base64_encode(force_bytes(self.customer.pk))
        token=default_token_generator.make_token(self.customer)
        url=reverse('password_reset_confirm',args=[uid,token])
        response=self.client.get(url,HTTP_HOST='salao.localhost')
        response=self.client.post(response.url,{'new_password1':'Nova!Senha2026Segura','new_password2':'Nova!Senha2026Segura'},HTTP_HOST='salao.localhost')
        self.assertContains(self.client.get(response.url,HTTP_HOST='salao.localhost'),'http://salao.localhost/login/?next=/conta/')
