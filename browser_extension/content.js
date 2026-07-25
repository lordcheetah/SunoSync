/**
 * SunoSync Token Helper — Content Script
 *
 * Runs in the ISOLATED world on suno.com pages and bridges the page-context
 * injected.js to the background worker.
 *
 * Security note: this script previously relayed any message that merely had
 * type === 'SUNOSYNC_TOKEN' straight to the background worker, so any script
 * running on the page could inject a token of its choosing. Messages are now
 * checked for origin and channel before being relayed.
 */

(function () {
    'use strict';

    const MSG_TYPE_TOKEN = 'SUNOSYNC_TOKEN';
    const MSG_TYPE_REFRESH = 'SUNOSYNC_REFRESH';
    const MSG_TYPE_STATUS = 'SUNOSYNC_STATUS';

    // Fresh per page load; handed to injected.js via a data attribute.
    const CHANNEL = crypto.randomUUID();

    const PAGE_ORIGIN = window.location.origin;

    // --- 1. Inject the page-context script ---
    function injectScript() {
        const script = document.createElement('script');
        script.src = chrome.runtime.getURL('injected.js');
        script.dataset.sunosyncChannel = CHANNEL;
        script.onload = function () {
            this.remove(); // Clean up the <script> tag after execution.
        };
        (document.head || document.documentElement).appendChild(script);
    }

    injectScript();

    function isTrustworthy(event) {
        if (event.source !== window) return false;
        if (event.origin !== PAGE_ORIGIN) return false;
        const data = event.data;
        if (!data || typeof data !== 'object') return false;
        return data.channel === CHANNEL;
    }

    // A Clerk session token is a JWT. Anything else is not worth relaying.
    function looksLikeJwt(token) {
        return typeof token === 'string'
            && token.length > 0
            && token.length <= 8192
            && /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$/.test(token);
    }

    // --- 2. Messages FROM the injected script (page context) ---
    window.addEventListener('message', function (event) {
        if (!isTrustworthy(event)) return;

        const data = event.data;

        if (data.type === MSG_TYPE_TOKEN) {
            if (!looksLikeJwt(data.token)) {
                console.warn('[SunoSync] Ignoring a malformed token from the page.');
                return;
            }
            chrome.runtime.sendMessage({
                action: 'token_received',
                token: data.token,
                timestamp: data.timestamp
            });
        }

        if (data.type === MSG_TYPE_STATUS) {
            chrome.runtime.sendMessage({
                action: 'status_update',
                status: String(data.status || ''),
                message: String(data.message || '')
            });
        }
    });

    // --- 3. Messages FROM the background worker ---
    chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
        // Only accept instructions from our own extension.
        if (!sender || sender.id !== chrome.runtime.id) return false;

        if (message.action === 'refresh_token') {
            window.postMessage({ type: MSG_TYPE_REFRESH, channel: CHANNEL }, PAGE_ORIGIN);
            sendResponse({ ok: true });
        }
        return false;
    });
})();
