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
            chat.replaceChildren();
            for (const message of data.messages) {
                const row = document.createElement('p');
                row.textContent = `${message.sent ? 'Enviada' : 'Recebida'}: ${message.text}`;
                chat.append(row);
            }
            status.textContent = data.messages.length ? 'Conversa atualizada.' : 'Nenhuma mensagem disponível. O histórico precisa estar habilitado na Evolution.';
        } catch (error) {
            status.textContent = error.message;
        } finally { busy = false; }
    }
    document.getElementById('refresh-chat').addEventListener('click', update);
    setInterval(update, 10000);
    update();
})();
