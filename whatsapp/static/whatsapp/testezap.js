(() => {
    const number = document.getElementById('id_whatsapp');
    const status = document.getElementById('chat-status');
    const chat = document.getElementById('chat-messages');
    let busy = false;
    async function update() {
        if (busy || document.hidden) return;
        busy = true;
        try {
            const url = new URL(window.location.href);
            url.search = new URLSearchParams({mensagens: '1', whatsapp: number.value});
            const response = await fetch(url, {headers: {'Accept': 'application/json'}});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Não foi possível consultar a conversa.');
            const testOutput = document.getElementById('roundtrip-status');
            if (testOutput && data.test) {
                testOutput.textContent = data.test.status === 'confirmado'
                    ? 'Envio e recebimento confirmados pela resposta do celular.'
                    : data.test.status === 'falha' ? `Falha no envio: ${data.test.error}`
                    : `Mensagem aceita pela API. Aguardando resposta com ${data.test.token}.`;
            }
            chat.replaceChildren();
            if (!data.messages.length) {
                const empty = document.createElement('div'); empty.className = 'conversation-empty';
                const title = document.createElement('strong'); title.textContent = 'Sua conversa começa aqui';
                const hint = document.createElement('p'); hint.textContent = 'Envie uma mensagem e responda pelo celular para acompanhar a conversa.';
                empty.append(title, hint); chat.append(empty);
            }
            for (const message of data.messages) {
                const row = document.createElement('article');
                row.className = `chat-bubble ${message.sent ? 'outgoing' : 'incoming'}`;
                const label = document.createElement('strong');
                label.textContent = `${message.sent ? 'Enviada' : 'Recebida'}${message.number ? ' · ' + message.number : ''}`;
                const body = document.createElement('p'); body.textContent = message.text;
                row.append(label, body);
                chat.append(row);
            }
            status.textContent = data.messages.length ? 'Conversa atualizada.' : 'Nenhuma mensagem recebida. Confira a configuração do webhook.';
            if (data.warning) status.textContent += ` Consulta da Evolution: ${data.warning}`;
        } catch (error) {
            status.textContent = error.message;
        } finally { busy = false; }
    }
    document.getElementById('refresh-chat').addEventListener('click', update);
    const diagnose = document.getElementById('diagnose-whatsapp');
    async function checkConnection() {
        if (document.hidden || (diagnose && diagnose.disabled)) return;
        const output = document.getElementById('diagnosis-status');
        const badge = document.getElementById('whatsapp-connection');
        const connectedNumber = document.getElementById('whatsapp-connection-number');
        if (diagnose) diagnose.disabled = true;
        if (output) output.textContent = 'Verificando…';
        try {
            const url = new URL(window.location.href);
            url.search = new URLSearchParams({diagnostico: '1'});
            const response = await fetch(url, {headers: {'Accept': 'application/json'}});
            const data = await response.json();
            if (!response.ok) throw new Error('Não foi possível consultar a conexão.');
            const online = data.status === 'open' && !data.error;
            const pending = data.status === 'connecting' && !data.error;
            const offline = data.configured === false || ['close', 'closed', 'missing'].includes(data.status);
            badge.className = `connection-status ${online ? 'online' : pending ? 'pending' : offline ? 'offline' : 'unknown'}`;
            badge.textContent = online ? 'WhatsApp conectado' : pending ? 'Conectando…' : offline ? 'WhatsApp desconectado' : 'Status indisponível';
            connectedNumber.textContent = online && data.number ? `Número conectado: ${data.number}` : '';
            if (output) output.textContent = data.error || `${data.instance}: ${data.status}. ${data.detail || ''}`;
        } catch (_) {
            badge.className = 'connection-status unknown';
            badge.textContent = 'Status indisponível';
            connectedNumber.textContent = '';
            if (output) output.textContent = 'Não foi possível consultar o diagnóstico. Verifique sua conexão ou entre novamente.';
        } finally { if (diagnose) diagnose.disabled = false; }
    }
    if (diagnose) diagnose.addEventListener('click', checkConnection);
    setInterval(checkConnection, 30000);
    checkConnection();
    setInterval(update, 10000);
    update();
})();
