
print(resultado)
PY
bash: cd: /var/www/html/combinado: No such file or directory
bash: venv/bin/python: No such file or directory
marcos@marcos-B550M-AORUS-ELITE:~$ venv/bin/python manage.py shell <<'PY'
from tenants.models import Tenant
from whatsapp.providers import get_provider
from usuarios.validators import normalizar_whatsapp

tenant = Tenant.objects.get(subdomain="x", ativo=True)
mensagem = "Olá! 😊 Já faz cerca de 30 dias desde o seu último corte de cabelo. Que tal renovar o visual? Estamos esperando por você! ✂️"
resultado = get_provider().send_text(
    tenant, normalizar_whatsapp("21990921092"), mensagem
)
print(resultado)
PY
bash: venv/bin/python: No such file or directory
marcos@marcos-B550M-AORUS-ELITE:~$ 
