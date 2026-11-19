from . import guide

CATEGORY = dict(id='qr-code', title='QR Code', icon='▦', description='Compartilhe o endereço da loja e de cada profissional.', tutorials=[
    guide('qr-loja', 'Salvar e compartilhar o QR Code da loja',
          'O QR Code público leva ao site do seu estabelecimento. Ele já é exibido ao abrir a página.',
          ['Abra QR Code da loja no menu.', 'No seletor, mantenha Loja. Confira o endereço exibido abaixo da imagem.',
           'Use Copiar endereço do site e cole o link em uma conversa do WhatsApp ou na sua divulgação.',
           'Para salvar a imagem, use o menu do navegador: clique com o botão direito no computador ou mantenha pressionada no celular e escolha salvar imagem, quando disponível.',
           'Antes de imprimir em cartões ou cartazes, teste a leitura com outro celular. Mantenha bom contraste e espaço livre em volta do código.'],
          'A tela atual oferece copiar o endereço, não um botão de compartilhamento direto pelo WhatsApp nem um botão próprio de download. A imagem pode ser salva pelo navegador.',
          [('Seleção', 'Loja'), ('Imagem', 'QR Code público gerado pelo sistema'), ('Divulgação', 'Copiar endereço → colar no WhatsApp')],
          ('qr-profissional', 'conectar-whatsapp'), 'qr code qrcode gerar salvar baixar imprimir compartilhar whatsapp loja'),
    guide('qr-profissional', 'Usar o QR Code de um profissional',
          'A mesma tela permite divulgar a página de um profissional específico.',
          ['Abra QR Code da loja.', 'Troque Loja pelo nome do profissional no seletor.',
           'Confira a imagem e o endereço atualizados. Copie o endereço ou salve a imagem pelo navegador.',
           'Teste a leitura antes de distribuir. O link leva à página pública correspondente ao profissional escolhido.'],
          'Para divulgar toda a equipe, volte a selecionar Loja. Não confunda esse QR Code de divulgação com o de conexão do WhatsApp.',
          [('Seletor', 'Escolha o profissional'), ('Resultado', 'QR Code e endereço individuais'), ('Uso', 'Cartão ou divulgação do profissional')],
          ('qr-loja', 'cadastrar-profissional'), 'qr code individual funcionário profissional compartilhar'),
])
