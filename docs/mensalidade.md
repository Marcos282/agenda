# Mensalidade — Checkout Pro

O administrador paga em `/painel/mensalidade/` pelo botão **Pagar 30 dias com Mercado Pago**. Cada pagamento aprovado acrescenta 30 dias; não há nova assinatura nem cobrança automática. O preço continua vindo de `PLATFORM_MONTHLY_PRICE` (padrão R$ 30,00).

## Configuração

No `.env` do servidor:

```dotenv
PLATFORM_MONTHLY_PRICE=30.00
MERCADO_PAGO_ACCESS_TOKEN=credencial-da-conta-vendedora
MERCADO_PAGO_WEBHOOK_SECRET=segredo-da-aplicacao
TENANT_BASE_DOMAIN=tacombinado.net
STORE_BASE_DOMAIN=tacombinado.net
```

Para cobranças reais, use as credenciais de produção da conta vendedora real. A troca para Checkout Pro não converte credenciais de teste em reais. O comprador se identifica no Mercado Pago: a aplicação não envia `payer` nem `payer_email`, e `MERCADO_PAGO_TEST_PAYER_EMAIL` não é usado nesse fluxo.

A preferência é criada por `POST /checkout/preferences`. O redirecionamento usa `init_point`, inclusive no teste com contas de teste, conforme as [orientações oficiais](https://www.mercadopago.com.br/developers/pt/news/2023/11/16/Questions-on-how-to-test-your-integration--). O prefixo do token não determina sozinho se a conta vendedora é real. O comprador deve ser diferente do vendedor.

Habilite o evento **Pagamentos (payment)** nos Webhooks da mesma aplicação. Cada preferência informa a URL HTTPS do estabelecimento: `https://<subdomínio>.tacombinado.net/integracoes/mercado-pago/webhook/`. Configure o segredo de assinatura correspondente. Nunca envie tokens por mensagem nem os adicione ao Git.

## Confirmação e prazo

- Cada tentativa guarda sua referência UUID, valor, recebedor e preferência no banco. Um checkout pendente é reaproveitado por até 24 horas. Depois, pode ser criado outro; notificações tardias de pagamentos válidos continuam sendo processadas.
- O webhook exige assinatura válida e consulta `/v1/payments/{id}` com a credencial do servidor. A volta do checkout também faz essa consulta, limitada ao estabelecimento autenticado.
- Parâmetros como `status=approved` na URL não liberam acesso. A aplicação verifica ID, status aprovado, BRL, valor, recebedor e referência da tentativa.
- O ID de pagamento é único no banco. Retorno e webhook repetidos não acrescentam dias novamente.
- O prazo passa a ser `max(vencimento atual, data local do pagamento) + 30 dias`.
- Após vencer, o administrador ainda pode acessar Mensalidade; novos agendamentos permanecem bloqueados até renovar.

O painel conserva o diagnóstico mascarado do envio/resposta e do último webhook. **Atualizar diagnóstico** consulta novamente os dados salvos. Nenhum dado de cartão é recebido pelo sistema.

## Transição das assinaturas anteriores

Novos pagamentos não usam `/preapproval`. Links pendentes de assinaturas antigas não aparecem no novo botão. Os dados e webhooks legados permanecem para reconciliar cobranças já existentes. Uma assinatura anterior com status `authorized` bloqueia o pagamento avulso e exibe o link de gerenciamento; cancele-a no Mercado Pago antes de renovar por Checkout Pro. Esta atualização não cancela contratos remotamente.

## Publicação

Envie os arquivos, incluindo `tenants/migrations/0008_plataformacheckout.py`, ao GitHub. No servidor:

```bash
cd /var/www/html/combinado
git pull
venv/bin/python manage.py migrate
sudo systemctl restart combinado
```

Aplique a migração antes de reiniciar. Testes automatizados usam respostas simuladas; não cobram cartões nem verificam as credenciais reais do servidor.
