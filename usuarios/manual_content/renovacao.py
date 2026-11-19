from . import guide

CATEGORY = dict(id='renovacao', title='Renovação', icon='🔄', description='Entenda a validade e mantenha as reservas disponíveis.', tutorials=[
    guide('renovar-assinatura', 'Consultar o vencimento e renovar',
          'A área Renovação mostra a validade do estabelecimento e as opções de pagamento disponíveis.',
          ['Abra Renovação no menu e confira a data de vencimento e os dias restantes.',
           'Novos cadastros têm 60 dias de validade inicial nesta versão: 30 dias de gratuidade e outros 30 dias de prazo inicial. Datas já cadastradas são preservadas.',
           'Quando o pagamento online estiver configurado, escolha Renovar por 30 dias e confira a prévia antes de seguir para o pagamento.',
           'Conclua o pagamento no Mercado Pago. O retorno do navegador sozinho não comprova aprovação: aguarde a confirmação validada pelo sistema.',
           'Após a confirmação, confira a nova validade e o histórico. Abra o comprovante de um pagamento aprovado quando precisar.'],
          'Os 30 dias são contados da data efetiva de aprovação, substituindo a validade anterior, inclusive se você pagar antes do vencimento. Não há acúmulo sobre a data antiga nem cobrança automática.',
          [('Pagamento aprovado em', '15/01/2027'), ('Nova validade', '14/02/2027'), ('Conferência', 'Data atualizada + histórico do pagamento')],
          ('cores-renovacao',), 'renovação renovar pagamento pagar assinatura vencimento comprovante validade'),
    guide('cores-renovacao', 'Entender as cores, a tolerância e a reativação',
          'O botão Renovação e os avisos acompanham a validade cadastrada para o seu estabelecimento.',
          ['Verde indica mais de 7 dias de validade. Azul aparece quando faltam de 4 a 7 dias; amarelo, de 0 a 3 dias.',
           'Depois do dia do vencimento, há três dias completos de tolerância, indicados em laranja. Nesse prazo, as reservas continuam liberadas.',
           'Após a tolerância, o botão fica vermelho e novas reservas são suspensas. O site público, os dados e agendamentos existentes continuam preservados.',
           'Você ainda pode entrar no painel, consultar agenda e clientes e acessar Renovação para pagar.',
           'Depois de um pagamento válido confirmado, a nova validade é aplicada automaticamente. Se ela estiver vigente, as reservas são liberadas e o aviso é atualizado.'],
          'O calendário da assinatura usa São Paulo. Exemplo: vencimento em 31/12 permite agendar até 03/01; o bloqueio começa em 04/01. O visitante recebe uma mensagem de indisponibilidade, sem informação sobre sua assinatura.',
          [('Verde', 'Mais de 7 dias'), ('Azul', '4 a 7 dias'), ('Amarelo', '0 a 3 dias'), ('Laranja', '3 dias de tolerância'), ('Vermelho', 'Novas reservas suspensas')],
          ('renovar-assinatura',), 'cores verde azul amarelo laranja vermelho tolerância bloqueio suspensão reativar desbloquear assinatura'),
])
