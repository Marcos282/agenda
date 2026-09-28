from django.urls import path
from . import views, agenda_views

app_name = 'painel'
urlpatterns = [
    path('', views.inicio, name='inicio'),
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
    path('profissionais/<int:profissional_id>/servicos/<int:pk>/editar/', views.vinculo_editar, name='vinculo_editar'),
    path('profissionais/<int:profissional_id>/agenda/', agenda_views.agenda, name='disponibilidades'),
    path('profissionais/<int:profissional_id>/agenda/novo/', views.disponibilidade_editar, name='disponibilidade_nova'),
    path('profissionais/<int:profissional_id>/agenda/<int:pk>/editar/', views.disponibilidade_editar, name='disponibilidade_editar'),
]
