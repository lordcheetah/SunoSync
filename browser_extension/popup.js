/**
 * SunoSync Token Helper — Popup Script
 *
 * Reads state from the background worker, updates the popup UI, and handles
 * pairing with the desktop app.
 */

(function () {
    'use strict';

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

    let pollTimer = null;

    function updateUI(state) {
        if (!state) return;

        // The pairing panel stays visible until a code has been stored.
        pairBox.classList.toggle('visible', !state.paired);
        unpairBtn.style.display = state.paired ? 'block' : 'none';
        refreshBtn.disabled = !state.paired;

        if (state.appConnected) {
            appDot.className = 'dot green';
            appText.textContent = 'Connected';
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

    function send(message) {
        return new Promise((resolve) => {
            chrome.runtime.sendMessage(message, (response) => {
                // Swallow "receiving end does not exist" while the worker wakes.
                void chrome.runtime.lastError;
                resolve(response);
            });
        });
    }

    async function refreshState() {
        updateUI(await send({ action: 'get_state' }));
    }

    pairBtn.addEventListener('click', async () => {
        const secret = pairInput.value.trim();
        if (!secret) {
            errorBox.textContent = 'Paste the pairing code from SunoSync Settings first.';
            errorBox.style.display = 'block';
            return;
        }

        pairBtn.textContent = 'Connecting...';
        pairBtn.disabled = true;

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
