# E-mail pelo Resend

O projeto usa o SMTP oficial do Resend através do backend do Django: `smtp.resend.com`, porta `465`, SSL, usuário `resend`, senha igual à chave de API. Não é necessário instalar um servidor de e-mail nem adicionar uma biblioteca Python.

## Preparar a conta

1. Adicione e verifique seu domínio no Resend, publicando os registros DNS fornecidos por ele.
2. Crie uma chave com permissão de envio para esse domínio.
3. Escolha um remetente pertencente ao domínio verificado, como `Tá Combinado <nao-responda@tacombinado.net>`.

## Configurar sem colocar a chave no chat ou no histórico do terminal

Na máquina local:

```bash
cd /home/marcos/barbe
myenv/bin/python manage.py configurar_resend
```

Após publicar esta versão do código no servidor:

```bash
cd /var/www/html/combinado
venv/bin/python manage.py configurar_resend
sudo systemctl restart combinado
```

O comando pede o remetente e a chave, ocultando a chave durante a digitação. Preserva os demais dados de `.local-settings.json` e grava o arquivo com permissão 600. O arquivo é ignorado pelo Git. O usuário do Django precisa ser o dono ou ter acesso ao arquivo (na instalação atual, `marcos`). Não há envio de teste automático.

Como alternativa, configure as variáveis no ambiente do processo:

```dotenv
RESEND_API_KEY=
RESEND_FROM_EMAIL=Tá Combinado <nao-responda@tacombinado.net>
```

Preencha a chave fora do repositório. As variáveis RESEND_* têm prioridade sobre o arquivo local. Quando há chave Resend, ele tem prioridade sobre EMAIL_HOST. Sem chave Resend, a configuração SMTP genérica permanece disponível; sem nenhuma configuração, o backend continua sendo console, sem entrega real.

A recuperação de senha usa automaticamente o remetente configurado. Os testes automatizados usam memória, sem enviar e-mails reais. A configuração só estará operacional depois de fornecer a chave e verificar o domínio no Resend.

Fontes: https://resend.com/changelog/smtp-service e https://resend.com/docs/dashboard/domains/introduction
