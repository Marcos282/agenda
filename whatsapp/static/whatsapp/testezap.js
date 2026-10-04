(() => {
    const number = document.getElementById('id_whatsapp');
    const status = document.getElementById('chat-status');
    const chat = document.getElementById('chat-messages');
    let busy = false;
    async function update() {
        if (busy || !number.value.trim() || document.hidden) return;
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
            for (const message of data.messages) {
                const row = document.createElement('p');
                row.textContent = `${message.sent ? 'Enviada' : 'Recebida'}: ${message.text}`;
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
    if (diagnose) diagnose.addEventListener('click', async () => {
        const output = document.getElementById('diagnosis-status');
        diagnose.disabled = true;
        output.textContent = 'Verificando…';
        try {
            const url = new URL(window.location.href);
            url.search = new URLSearchParams({diagnostico: '1'});
            const response = await fetch(url, {headers: {'Accept': 'application/json'}});
            const data = await response.json();
            output.textContent = data.error || `${data.instance}: ${data.status}. ${data.detail || ''}`;
        } catch (_) { output.textContent = 'Não foi possível consultar o diagnóstico. Verifique sua conexão ou entre novamente.'; }
        finally { diagnose.disabled = false; }
    });
    setInterval(update, 10000);
    update();
})();
