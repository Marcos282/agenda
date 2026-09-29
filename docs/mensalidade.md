# Mensalidade da plataforma

O botão **Mensalidade**, ao lado de **QR Code da loja**, abre `/painel/mensalidade/`. A página é exclusiva do administrador do estabelecimento e apresenta o plano de uso da plataforma.

## Configuração do checkout

Crie o plano mensal na conta recebedora da plataforma no Mercado Pago. Configure no ambiente do servidor:

```dotenv
MERCADO_PAGO_SUBSCRIPTION_PLAN_ID=identificador_do_plano
PLATFORM_MONTHLY_PRICE=valor_regular_do_plano
```

Configure o preço regular com ponto decimal, somente quando definido. A oferta informada é de R$ 29,90/mês para os 20 primeiros cadastros. A oferta não é exibida na página Mensalidade. A atribuição e o controle das 20 vagas dependem da futura configuração singleton e não são simulados nesta entrega. `PLATFORM_MONTHLY_PRICE` é informativo: deve corresponder ao preço configurado no Mercado Pago. Sem valor, a página informa que o preço deve ser consultado no checkout. O ID vem do parâmetro `preapproval_plan_id` do link de assinatura. As variáveis também podem ser configuradas no arquivo local não versionado `.local-settings.json`; o ambiente tem precedência.

A página monta um link HTTPS para o checkout do plano no domínio brasileiro do Mercado Pago. O usuário confere valor e condições e autoriza a assinatura no provedor. Não são coletados cartão, senha ou Access Token no painel. Sem ID de plano válido, a tela mostra “Em configuração” e o botão de pagamento fica desabilitado.

## Limites desta entrega

A integração atual oferece o acesso ao checkout hospedado. Ela não cria assinaturas via API, não associa automaticamente uma assinatura ao tenant e não sincroniza pagamentos, vencimentos, cancelamentos ou histórico. Abrir o checkout ou voltar dele não altera o status de pagamento nem o acesso ao sistema. O painel não declara que uma assinatura está ativa ou paga. Quem já assinou deve consultar a assinatura no Mercado Pago antes de contratar novamente.

Para automatizar o controle financeiro, será necessário acrescentar a vinculação de cada assinatura ao estabelecimento, credenciais do servidor, consulta à API e webhooks autenticados.

Referência oficial: [Plano de assinatura e link de checkout (`init_point`)](https://www.mercadopago.com.br/developers/pt/reference/online-payments/subscriptions/create-preapproval-plan/post).

## Expiração do estabelecimento

`Tenant.expira_em` armazena a data de expiração do estabelecimento pagante, e não do consumidor que agenda serviços. É preenchida automaticamente com a data local do cadastro mais 30 dias, considerando o fuso do estabelecimento. Cadastros antigos sem prazo recebem a mesma regra a partir da data original; datas já definidas são preservadas. O superusuário edita o campo em **Administração da plataforma → Tenants**, onde também aparece na listagem e no filtro. A página Mensalidade exibe a data e um contador calculado a cada acesso: 30, 29, 28… dias. No vencimento mostra “Expira hoje” e depois “Prazo expirado”, sempre sem números negativos. O administrador do estabelecimento não pode alterar a data. O formulário público de registro não aceita uma expiração enviada pelo visitante.

A data ainda não bloqueia acesso nem se renova ao retornar do Mercado Pago. Editar o cadastro não reinicia o prazo. A política de vencimento e renovação e a tabela singleton de preços serão conectadas posteriormente.
