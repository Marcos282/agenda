(() => {
    const input = document.getElementById('id_mensagem_confirmacao');
    const output = document.getElementById('confirmation-preview');
    const data = document.getElementById('confirmation-values');
    if (!input || !output || !data) return;
    const values = JSON.parse(data.textContent);
    function update() {
        output.textContent = input.value.replace(/{{|}}|{([^{}]+)}/g, (match, key) => {
            if (match === '{{') return '{';
            if (match === '}}') return '}';
            return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : match;
        });
    }
    input.addEventListener('input', update);
    update();
})();
