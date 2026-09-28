from barbe.admin import site
from django.urls import path, include
from usuarios import views

urlpatterns = [
    path('painel/', include('painel.urls')),
    path('', views.home, name='home'),
    path('cadastro/', views.cadastro, name='cadastro'),
    path('login/', views.entrar, name='login'),
    path('logout/', views.sair, name='logout'),
    path('conta/', views.conta, name='conta'),
    path('admin/', site.urls),
]
