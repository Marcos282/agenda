(() => {
    const dialog = document.querySelector('.logo-dialog');
    if (!dialog) return;

    const find = (name) => dialog.querySelector(`[data-logo-${name}]`);
    const form = dialog.querySelector('form');
    const fields = find('fields');
    const credits = find('credits');
    const message = find('message');
    const loading = find('loading');
    const result = find('result');
    const generate = find('generate');
    const regenerate = find('regenerate');
    const apply = find('apply');
    const download = find('download');
    const csrf = form.elements.csrfmiddlewaretoken.value;
    let statusUrl = dialog.dataset.activeUrl;
    let pending = false;
    let hasCredits = !generate.disabled;
    let timer;

    async function request(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: {'Accept': 'application/json', 'X-CSRFToken': csrf},
            cache: 'no-store',
        });
        const data = await response.json();
        if (!response.ok) {
            const errors = Object.values(data.errors || {}).flat().map((error) => error.message);
            throw new Error(data.message || errors.join(' ') || dialog.dataset.networkError);
        }
        return data;
    }

    function setPending(value) {
        pending = value;
        loading.hidden = !value;
        fields.disabled = value;
        generate.disabled = value || !hasCredits;
        regenerate.disabled = generate.disabled;
        apply.disabled = value;
    }

    function showJob(data) {
        credits.textContent = data.credits_message;
        hasCredits = data.credits > 0;
        message.textContent = data.message || '';
        if (data.status === 'queued' || data.status === 'running') {
            statusUrl = data.status_url;
            setPending(true);
            if (dialog.open) timer = setTimeout(poll, 2000);
            return;
        }

        statusUrl = null;
        form.elements.request_id.value = data.next_request_id;
        const ready = data.status === 'ready';
        result.hidden = !ready;
        apply.hidden = !ready;
        download.hidden = !ready;
        regenerate.hidden = !ready;
        generate.hidden = ready;
        if (ready) {
            result.querySelector('img').src = data.image_url;
            apply.dataset.url = data.apply_url;
            download.href = data.download_url;
        }
        setPending(false);
    }

    async function poll() {
        if (!statusUrl || !dialog.open) return;
        try {
            showJob(await request(statusUrl));
        } catch {
            message.textContent = dialog.dataset.networkError;
            if (dialog.open) timer = setTimeout(poll, 5000);
        }
    }

    document.querySelector('[data-open-logo]').addEventListener('click', () => {
        dialog.showModal();
        if (statusUrl && !timer) {
            setPending(true);
            poll();
        }
    });

    dialog.querySelectorAll('[data-close-logo]').forEach((button) => {
        button.addEventListener('click', () => dialog.close());
    });
    dialog.addEventListener('close', () => {
        clearTimeout(timer);
        timer = null;
    });

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (pending || !hasCredits) return;
        const body = new FormData(form);
        setPending(true);
        message.textContent = '';
        try {
            showJob(await request(form.action, {method: 'POST', body}));
        } catch (error) {
            message.textContent = error instanceof SyntaxError ? dialog.dataset.networkError : error.message;
            setPending(false);
        }
    });

    apply.addEventListener('click', async () => {
        apply.disabled = true;
        try {
            const data = await request(apply.dataset.url, {method: 'POST'});
            message.textContent = data.message;
            const savedLogo = document.querySelector('[data-saved-logo]');
            savedLogo.querySelector('[data-saved-logo-link]').href = data.saved_logo_url;
            savedLogo.querySelector('[data-saved-logo-thumbnail]').src = data.saved_logo_url;
            savedLogo.hidden = false;
            savedLogo.querySelector('[data-saved-logo-success]').hidden = false;
            const upload = document.querySelector('[data-logo-upload]');
            upload.querySelector('[data-alter-logo]').hidden = false;
            upload.open = false;
        } catch {
            message.textContent = dialog.dataset.networkError;
        } finally {
            apply.disabled = pending;
        }
    });
})();
