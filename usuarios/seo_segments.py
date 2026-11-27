from django.utils.translation import gettext_lazy as _


SEGMENTS = {
    'barbearia': {
        'label': _('Barbearias'),
        'title': _('Agenda online para barbearias'),
        'description': _('Organize cortes e barbas por profissional, divulgue horários disponíveis e receba reservas online na sua barbearia com o Tá Combinado.'),
        'intro': _('Quando o cliente quer marcar corte e barba, a barbearia pode mostrar pelo mesmo link quem atende, quais serviços oferece e quais horários ainda estão livres.'),
        'benefits': [
            (_('Reserve o tempo certo na cadeira'), _('Cadastre corte, barba e o combo como serviços com preços e durações próprios. Assim, a reserva ocupa o intervalo definido para cada atendimento.')),
            (_('Organize a agenda de cada barbeiro'), _('Associe os serviços a quem os realiza e ajuste os períodos de trabalho de cada pessoa. O cliente escolhe o profissional e um horário disponível.')),
            (_('Divulgue a agenda no balcão'), _('Exponha o QR Code da loja para que quem já passou pela barbearia consiga marcar o próximo corte pelo celular.')),
        ],
    },
    'salao-de-beleza': {
        'label': _('Salões de beleza'),
        'title': _('Agenda online para salões de beleza'),
        'description': _('Organize serviços de beleza com durações diferentes, mostre a equipe e receba reservas para o seu salão na página do Tá Combinado.'),
        'intro': _('Uma escova rápida e uma coloração longa pedem horários diferentes. Com o Tá Combinado, o salão apresenta os serviços e permite que cada cliente reserve com quem os realiza.'),
        'benefits': [
            (_('Mostre as opções antes da reserva'), _('Publique serviços como escova, penteado ou manicure com preço e duração definidos. O cliente confere as opções no catálogo do salão.')),
            (_('Distribua os horários por especialidade'), _('Vincule os serviços aos profissionais e configure os períodos individuais. A equipe pode consultar as reservas do dia no painel.')),
            (_('Compartilhe a página do salão'), _('Adicione o link da loja à bio das redes sociais e envie-o quando alguém perguntar pelos próximos horários. A reserva pode ser feita sem criar conta.')),
        ],
    },
    'podologia': {
        'label': _('Podólogos'),
        'title': _('Agenda online para podólogos'),
        'description': _('Disponibilize horários de podologia, organize a duração de cada atendimento e configure lembretes pelo WhatsApp com o Tá Combinado.'),
        'intro': _('Quem precisa organizar a próxima visita pode consultar os horários publicados pelo podólogo e reservar pelo celular, mesmo fora do expediente.'),
        'benefits': [
            (_('Planeje o tempo entre atendimentos'), _('Defina a duração dos serviços no catálogo e configure períodos e intervalos para acomodar a preparação do espaço.')),
            (_('Facilite a marcação da próxima visita'), _('Compartilhe o endereço da sua página ao final do atendimento. O cliente pode escolher outra data conforme os horários disponíveis.')),
            (_('Envie lembretes de horário'), _('Conecte o WhatsApp da loja e configure a antecedência do lembrete para avisar o cliente antes da visita.')),
        ],
    },
    'dentistas': {
        'label': _('Dentistas'),
        'title': _('Agenda online para dentistas'),
        'description': _('Organize os horários da equipe do consultório e ofereça reserva online para atendimentos selecionados com o Tá Combinado.'),
        'intro': _('O consultório pode publicar horários de atendimentos selecionados e enviar um link para quem precisa marcar. A equipe acompanha as reservas na agenda diária.'),
        'benefits': [
            (_('Escolha quais horários oferecer'), _('Configure períodos e intervalos por profissional para publicar somente as janelas disponíveis para reservas no site.')),
            (_('Organize os tipos de agendamento'), _('Associe os atendimentos do catálogo aos profissionais responsáveis e defina as respectivas durações, como em uma avaliação inicial.')),
            (_('Use o WhatsApp para lembrar a visita'), _('Com o número do consultório conectado, configure a mensagem e a antecedência do lembrete. Na reserva, a pessoa informa nome e WhatsApp.')),
        ],
    },
    'estetica': {
        'label': _('Clínicas de estética'),
        'title': _('Agenda online para clínicas de estética'),
        'description': _('Apresente os serviços da sua clínica de estética, organize horários por profissional e receba agendamentos online com o Tá Combinado.'),
        'intro': _('Quem conhece a clínica pelas redes sociais pode abrir o catálogo, conferir preços e reservar um horário com a profissional que oferece o serviço.'),
        'benefits': [
            (_('Apresente seus serviços em um só lugar'), _('Divulgue opções como limpeza de pele e design de sobrancelhas na página da clínica, com os preços e durações configurados pela equipe.')),
            (_('Planeje o tempo de cada sessão'), _('Configure durações diferentes para os serviços e inclua intervalos nos períodos de atendimento quando precisar preparar o espaço.')),
            (_('Consulte os agendamentos do dia'), _('Acompanhe no painel as reservas por profissional e divulgue a página da clínica por link ou QR Code.')),
        ],
    },
    'autonomos': {
        'label': _('Profissionais autônomos'),
        'title': _('Agenda online para profissionais autônomos'),
        'description': _('Divulgue seus serviços com um link próprio, controle os horários que oferece e receba reservas online como profissional autônomo.'),
        'intro': _('Quem atende por conta própria pode compartilhar os horários disponíveis sem interromper um serviço em andamento para responder a cada pedido de agendamento.'),
        'benefits': [
            (_('Publique apenas os períodos em que atende'), _('Configure dias, janelas e intervalos na agenda para conciliar as reservas com outras atividades da semana.')),
            (_('Dê um endereço aos seus serviços'), _('Crie um catálogo com nome, preço e duração de cada opção. Compartilhe a página no perfil profissional ou em uma mensagem.')),
            (_('Organize os atendimentos mesmo sem equipe'), _('Consulte as reservas na agenda diária e, se conectar seu WhatsApp, configure lembretes automáticos para os clientes.')),
        ],
    },
}
