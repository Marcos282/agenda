from barbe.admin import site
from django.urls import path, include
from usuarios import views, registro, login_transfer
from django.views.generic import TemplateView
from pagamentos.views import webhook
from whatsapp.console import testezap, testes
from whatsapp.inbox_views import receive

urlpatterns = [
    path('teste/', testes, {'route': 'teste'}, name='teste'),
    path('teste/receber/', receive, name='whatsapp_test_receive_single'),
    path('testes/whatsapp/receber', receive, name='whatsapp_test_receive'),
    path('testes', testes, name='testes'),
    path('testes/', testes),
    path('testezap', testezap, name='testezap'),
    path('testezap/', testezap),
    path('integracoes/mercado-pago/webhook/', webhook, name='mercado_pago_webhook'),
    path('registro', registro.registro, name='registro'),
    path('registro/', registro.registro),
    path('registro/concluido/', registro.registro_concluido, name='registro_concluido'),
    path('lembrar-senha/', registro.RecuperarSenha.as_view(), name='lembrar_senha'),
    path('lembrar-senha/enviado/', TemplateView.as_view(template_name='usuarios/senha_email_enviado.html'), name='senha_email_enviado'),
    path('redefinir-senha/<uidb64>/<token>/', registro.RedefinirSenha.as_view(), name='password_reset_confirm'),
    path('senha-redefinida/', registro.senha_redefinida, name='senha_redefinida'),
    path('agendamentos/', include('agenda.urls')),
    path('painel/', include('painel.urls')),
    path('', views.home, name='home'),
    path('inicio/', views.home, name='inicio'),
    path('profissional/<int:profissional_id>/', views.home, name='home_profissional'),
    path('profissional/<int:pk>/foto/', views.profissional_foto_publica, name='profissional_foto_publica'),
    path('loja/', views.loja, name='loja'),
    path('loja/<int:item_id>/', views.loja, name='loja_item'),
    path('cadastro/', views.cadastro, name='cadastro'),
    path('login/continuar/', login_transfer.concluir, name='login_continuar'),
    path('login/', views.entrar, name='login'),
    path('logout/', views.sair, name='logout'),
    path('conta/', views.conta, name='conta'),
    path('admin/', site.urls),
]
