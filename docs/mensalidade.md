# Acesso ao sistema por 30 dias — Checkout Pro

O administrador usa **Acesso ao sistema** no painel (`/painel/mensalidade/`) para comprar 30 dias. O preço padrão é R$ 30,00. É um pagamento avulso: não há assinatura, cartão salvo pelo sistema ou cobrança automática. O SDK oficial `mercadopago==3.6.0` cria a preferência e redireciona o comprador ao `init_point` do Checkout Pro.

O saldo de dias nunca fica negativo: depois do vencimento, permanece em zero e o acesso é marcado como expirado. Uma aprovação adiciona 30 dias a `max(hoje, vencimento atual)`, considerando o fuso do estabelecimento. Cada identificador de pagamento só concede acesso uma vez, inclusive quando o webhook e o retorno chegam juntos. Pagamentos pendentes ou recusados não concedem acesso. Duas cobranças distintas aprovadas concedem dois períodos de 30 dias.

## Configuração

Instale as dependências e aplique as migrações:

```bash
myenv/bin/python -m pip install -r requirements.txt
myenv/bin/python manage.py migrate
```

Configure no `.env` ou em `.local-settings.json` (arquivos ignorados pelo Git):

```dotenv
PLATFORM_ACCESS_PRICE=30.00
MERCADO_PAGO_ACCESS_TOKEN=seu-access-token
MERCADO_PAGO_WEBHOOK_SECRET=segredo-da-assinatura-do-webhook
MERCADO_PAGO_PUBLIC_URL=https://seu-dominio-publico
MERCADO_PAGO_LIVE_MODE=false
```

`PLATFORM_MONTHLY_PRICE` continua como fallback para o preço existente, sem implementar recorrência. O Access Token e o segredo do webhook são diferentes. Nenhum deles vai para o navegador. A configuração exige uma URL HTTPS e as duas credenciais antes de habilitar o botão.

Em **Mercado Pago Developers → Suas integrações → sua aplicação → Webhooks**, configure o evento **Pagamentos (payment)** com a URL:

```text
https://seu-dominio-publico/integracoes/mercado-pago/webhook/
```

O cadastro do webhook é feito no painel do Mercado Pago. A integração usa o webhook da aplicação, sem o campo legado `notification_url` na preferência. Use as credenciais da mesma aplicação/conta vendedora configurada no painel.

## Teste local com ngrok

Mantenha o Django e o ngrok rodando na mesma porta:

```bash
myenv/bin/python manage.py runserver 8001
ngrok http 8001
```

A configuração local atual usa:

```dotenv
DEV_PUBLIC_HOST=evergreen-distance-playmaker.ngrok-free.dev
DEV_TENANT_SUBDOMAIN=marcos
MERCADO_PAGO_PUBLIC_URL=https://evergreen-distance-playmaker.ngrok-free.dev
MERCADO_PAGO_LIVE_MODE=false
```

Quando `DEBUG=True`, o host mostra `marcos` para visitantes. As rotas de cadastro ficam disponíveis no mesmo túnel; após o login, o estabelecimento é definido pela conta autenticada, permitindo testar também novos cadastros sem subdomínios extras. Os domínios normais mantêm a separação por subdomínio. Entre com o administrador de Marcos em `https://evergreen-distance-playmaker.ngrok-free.dev/login/` e abra **Acesso ao sistema**. Se o domínio do túnel mudar, atualize as configurações locais e o webhook no Mercado Pago. Reinicie o Django após editar as configurações locais.

Use contas e meios de pagamento de teste conforme a documentação oficial. Comprador e vendedor devem ser contas distintas. A aplicação não envia um e-mail de comprador fixo: o usuário se identifica no checkout. O modo de teste aceita apenas pagamentos cujo `live_mode` retornado pelo Mercado Pago seja `false`, e pode alterar o vencimento do estabelecimento de teste. Não use uma compra real para validar este ambiente.

Para produção, configure a URL pública definitiva, as credenciais de produção e `MERCADO_PAGO_LIVE_MODE=true`. Desabilite `DEBUG`. O domínio público precisa ser atendido pelo Django e os retornos usam `https://<estabelecimento>.<TENANT_BASE_DOMAIN>/painel/mensalidade/`.

## Confirmação e operação

O webhook valida a assinatura com o SDK e consulta o pagamento autenticado na API. Confere referência, valor, BRL, recebedor, ambiente e a preferência da ordem antes de conceder acesso. Os parâmetros de retorno do navegador, como `status=approved`, nunca são prova de pagamento. O histórico mostra as últimas dez cobranças do estabelecimento, e o Django Admin permite consultar os registros sem alterá-los.

Notificações duplicadas são idempotentes. Falhas temporárias da API respondem HTTP 503 para permitir nova tentativa do provedor; atualizar a página de retorno também tenta confirmar novamente. Se for necessária uma reconciliação manual:

```bash
myenv/bin/python manage.py reconciliar_pagamento ID_DO_PAGAMENTO
```

Reembolsos e contestações atualizam o histórico, mas não retiram automaticamente dias já concedidos. Nesses casos, o administrador da plataforma deve avaliar e ajustar a validade manualmente. Um pagamento parcialmente reembolsado não concede um novo período.

As migrações antigas permanecem como histórico. A integração atual está no app `pagamentos` e não reaproveita os contratos ou dados da implementação removida.

## Referências oficiais

- [SDK Python](https://github.com/mercadopago/sdk-python)
- [Criar preferência do Checkout Pro](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/create-payment-preference)
- [Notificações e validação de assinatura](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/payment-notifications)
