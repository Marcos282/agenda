from django.urls import path
from . import customer_views as views

app_name = 'agenda'
urlpatterns = [
    path('', views.meus_agendamentos, name='meus'),
    path('acompanhar/<uuid:token>/', views.acompanhar, name='acompanhar'),
    path('servico/<int:oferta_id>/', views.escolher_data, name='escolher_data'),
    path('servico/<int:oferta_id>/<str:dia>/horarios/', views.horarios_atualizar, name='horarios_atualizar'),
    path('servico/<int:oferta_id>/<str:dia>/', views.horarios, name='horarios'),
    path('<int:pk>/', views.detalhe, name='detalhe'),
]
