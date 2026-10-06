from django.urls import path, re_path
from django.views.generic import RedirectView
from . import views, agenda_views, agendamento_views, cliente_views, loja_qrcode_views, mensalidade_views

from whatsapp.views import configuracao_whatsapp
from whatsapp.console import testes

app_name = 'painel'
urlpatterns = [
    path('mensalidade/comprovantes/<str:payment_id>/', mensalidade_views.comprovante, name='comprovante_pagamento'),
    path('mensalidade/', mensalidade_views.mensalidade, name='mensalidade'),
    path('meu-cadastro/', views.meu_cadastro, name='meu_cadastro'),
    path('loja/qr/', loja_qrcode_views.loja_qrcode, name='loja_qrcode'),
    path('loja/qr.png', loja_qrcode_views.loja_qrcode_imagem, name='loja_qrcode_imagem'),
    path('loja/profissional/<int:profissional_id>/qr.png', loja_qrcode_views.profissional_qrcode_imagem, name='profissional_qrcode_imagem'),
    path('whatsapp/', configuracao_whatsapp, name='whatsapp'),
    path('testes/', testes, {'route': 'painel:testes'}, name='testes'),
    re_path(r'^whatsapp/testes/?$', RedirectView.as_view(pattern_name='painel:testes', query_string=True)),
    path('', views.inicio, name='inicio'),
    path('agendamentos/novo/', agendamento_views.novo, name='agendamento_novo'),
    path('agendamentos/<int:pk>/cancelar/', agendamento_views.cancelar_agendamento, name='agendamento_cancelar'),
    path('agendamentos/<int:pk>/atraso/', agendamento_views.atraso, name='agendamento_atraso'),
    path('agendamentos/<int:pk>/falta/', agendamento_views.falta, name='agendamento_falta'),
    path('agendamentos/<int:pk>/concluir/', agendamento_views.concluir, name='agendamento_concluir'),
    path('clientes/whatsapp/<str:whatsapp>/bloqueio/', cliente_views.whatsapp_bloqueio, name='whatsapp_bloqueio'),
    path('clientes/', cliente_views.lista, name='clientes'),
    path('clientes/whatsapp/<str:whatsapp>/', cliente_views.whatsapp_historico, name='whatsapp_historico'),
    path('clientes/contatos/<int:pk>/', cliente_views.contato_historico, name='contato_historico'),
    path('clientes/<int:pk>/', cliente_views.historico, name='cliente_historico'),
    path('agenda/dados/', agenda_views.agenda_dados, name='agenda_dados'),
    path('agenda/', agenda_views.agenda, name='agenda'),
    path('configuracoes/', views.configuracoes, name='configuracoes'),
    path('profissionais/', views.profissionais, name='profissionais'),
    path('profissionais/novo/', views.profissional_editar, name='profissional_novo'),
    path('profissionais/<int:pk>/editar/', views.profissional_editar, name='profissional_editar'),
    path('profissionais/<int:pk>/foto/', views.profissional_foto, name='profissional_foto'),
    path('servicos/', views.servicos, name='servicos'),
    path('servicos/novo/', views.servico_editar, name='servico_novo'),
    path('servicos/<int:pk>/editar/', views.servico_editar, name='servico_editar'),
    path('profissionais/<int:profissional_id>/servicos/', views.vinculos, name='vinculos'),
    path('profissionais/<int:profissional_id>/servicos/novo/', views.vinculo_editar, name='vinculo_novo'),
    path('profissionais/<int:profissional_id>/servicos/<int:pk>/disponibilidade/', views.vinculo_disponibilidade, name='vinculo_disponibilidade'),
    path('profissionais/<int:profissional_id>/servicos/<int:pk>/editar/', views.vinculo_editar, name='vinculo_editar'),
    path('profissionais/<int:profissional_id>/agenda/', agenda_views.agenda, name='disponibilidades'),
    path('profissionais/<int:profissional_id>/agenda/novo/', views.disponibilidade_editar, name='disponibilidade_nova'),
    path('profissionais/<int:profissional_id>/agenda/<int:pk>/editar/', views.disponibilidade_editar, name='disponibilidade_editar'),
]
