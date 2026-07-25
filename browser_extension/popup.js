/**
 * SunoSync Token Helper — Popup Script
 *
 * Reads state from the background worker, updates the popup UI, and handles
 * pairing with the desktop app.
 */

(function () {
    'use strict';

    // See background.js: Firefox's `chrome` alias is callback-based, so prefer
    // the promise-based `browser` namespace when it exists.
    const api = (typeof globalThis.browser !== 'undefined' && globalThis.browser.runtime)
        ? globalThis.browser
        : globalThis.chrome;

    // Firefox MV3 withholds host permissions until the user grants them, and
    // permissions.request() must run from a user gesture — so it lives here in
    // the popup rather than in the background worker.
    const REQUIRED_ORIGINS = [
        'https://suno.com/*',
        'https://*.suno.com/*',
        'http://127.0.0.1:38945/*'
    ];

    const appDot = document.getElementById('app-dot');
    const appText = document.getElementById('app-text');
    const sunoDot = document.getElementById('suno-dot');
    const sunoText = document.getElementById('suno-text');
    const lastRefresh = document.getElementById('last-refresh');
    const errorBox = document.getElementById('error-box');
    const refreshBtn = document.getElementById('refresh-btn');
    const checkBtn = document.getElementById('check-btn');
    const pairBox = document.getElementById('pair-box');
    const pairInput = document.getElementById('pair-input');
    const pairBtn = document.getElementById('pair-btn');
    const unpairBtn = document.getElementById('unpair-btn');
    const permBox = document.getElementById('perm-box');
    const permBtn = document.getElementById('perm-btn');

    let pollTimer = null;

    async function requestHostPermissions() {
        try {
            if (await api.permissions.contains({ origins: REQUIRED_ORIGINS })) {
                return true;
            }
            return await api.permissions.request({ origins: REQUIRED_ORIGINS });
        } catch (err) {
            console.error('[SunoSync] Permission request failed:', err);
            return false;
        }
    }

    function updateUI(state) {
        if (!state) return;

        // Firefox only. On Chrome hostPermissions is always true, so this stays
        // hidden and the pairing flow is unchanged.
        const needsPermission = state.hostPermissions === false;
        permBox.classList.toggle('visible', needsPermission);

        // The pairing panel stays visible until a code has been stored.
        pairBox.classList.toggle('visible', !state.paired);
        unpairBtn.style.display = state.paired ? 'block' : 'none';
        refreshBtn.disabled = !state.paired;

        if (state.appConnected) {
            appDot.className = 'dot green';
            appText.textContent = 'Connected';
        } else if (needsPermission) {
            appDot.className = 'dot yellow';
            appText.textContent = 'Needs access';
        } else if (!state.paired) {
            appDot.className = 'dot yellow';
            appText.textContent = 'Not paired';
        } else {
            appDot.className = 'dot red';
            appText.textContent = 'Disconnected';
        }

        if (state.sunoLoggedIn) {
            sunoDot.className = 'dot green';
            sunoText.textContent = 'Logged In';
        } else {
            sunoDot.className = 'dot gray';
            sunoText.textContent = 'Not Detected';
        }

        if (state.lastRefresh) {
            const date = new Date(state.lastRefresh);
            const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);

            if (diffSec < 60) {
                lastRefresh.textContent = diffSec + 's ago';
            } else if (diffSec < 3600) {
                lastRefresh.textContent = Math.floor(diffSec / 60) + 'm ago';
            } else {
                lastRefresh.textContent = date.toLocaleTimeString();
            }
        } else {
            lastRefresh.textContent = '—';
        }

        if (state.lastError && !state.appConnected) {
            errorBox.textContent = state.lastError;
            errorBox.style.display = 'block';
        } else {
            errorBox.style.display = 'none';
        }
    }

    /**
     * Send a message to the background worker.
     *
     * Promise-based rather than callback-based: Firefox's browser.runtime
     * .sendMessage does not accept a callback at all, so the previous callback
     * form never resolved there and the popup silently rendered nothing.
     * Chrome MV3 also returns a promise when no callback is passed.
     */
    async function send(message) {
        try {
            return await api.runtime.sendMessage(message);
        } catch (err) {
            // Commonly "receiving end does not exist" while the worker wakes up.
            console.debug('[SunoSync] sendMessage failed:', err);
            return undefined;
        }
    }

    async function refreshState() {
        updateUI(await send({ action: 'get_state' }));
    }

    permBtn.addEventListener('click', async () => {
        permBtn.textContent = 'Requesting...';
        permBtn.disabled = true;

        const granted = await requestHostPermissions();

        permBtn.textContent = 'Grant access';
        permBtn.disabled = false;

        if (!granted) {
            errorBox.textContent =
                'Access was declined. SunoSync cannot receive your token without it.';
            errorBox.style.display = 'block';
            return;
        }
        updateUI(await send({ action: 'check_app' }));
    });

    pairBtn.addEventListener('click', async () => {
        const secret = pairInput.value.trim();
        if (!secret) {
            errorBox.textContent = 'Paste the pairing code from SunoSync Settings first.';
            errorBox.style.display = 'block';
            return;
        }

        pairBtn.textContent = 'Connecting...';
        pairBtn.disabled = true;

        // Ask for host access first: on Firefox the bridge is unreachable
        // without it, and this click is the user gesture the API requires.
        await requestHostPermissions();
        const state = await send({ action: 'set_pairing_secret', secret });

        pairBtn.textContent = 'Save & Connect';
        pairBtn.disabled = false;
        pairInput.value = '';
        updateUI(state);
    });

    unpairBtn.addEventListener('click', async () => {
        updateUI(await send({ action: 'set_pairing_secret', secret: '' }));
    });

    pairInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') pairBtn.click();
    });

    refreshBtn.addEventListener('click', async () => {
        refreshBtn.textContent = 'Refreshing...';
        refreshBtn.disabled = true;

        await send({ action: 'manual_refresh' });
        setTimeout(() => {
            refreshBtn.textContent = 'Refresh Token Now';
            refreshBtn.disabled = false;
            refreshState();
        }, 2000);
    });

    checkBtn.addEventListener('click', async () => {
        checkBtn.textContent = 'Checking...';
        checkBtn.disabled = true;

        updateUI(await send({ action: 'check_app' }));

        checkBtn.textContent = 'Check Connection';
        checkBtn.disabled = false;
    });

    refreshState();
    pollTimer = setInterval(refreshState, 5000);
    window.addEventListener('unload', () => clearInterval(pollTimer));
})();
