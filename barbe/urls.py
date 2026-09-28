from barbe.admin import site
from django.urls import path, include
from usuarios import views

urlpatterns = [
    path('painel/', include('painel.urls')),
    path('', views.home, name='home'),
    path('profissional/<int:profissional_id>/', views.home, name='home_profissional'),
    path('loja/', views.loja, name='loja'),
    path('loja/<int:item_id>/', views.loja, name='loja_item'),
    path('cadastro/', views.cadastro, name='cadastro'),
    path('login/', views.entrar, name='login'),
    path('logout/', views.sair, name='logout'),
    path('conta/', views.conta, name='conta'),
    path('admin/', site.urls),
]
