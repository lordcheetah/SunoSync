/**
 * SunoSync Token Helper — Injected Script
 *
 * Runs in the PAGE context (same world as suno.com's own code) so it can reach
 * window.Clerk and call getToken(). Talks to the content script via postMessage.
 *
 * Security note: this script previously posted the session JWT with a target
 * origin of '*', which broadcast the token to every frame on the page,
 * including cross-origin iframes and any third-party script that had installed
 * a message listener. Messages are now addressed to the page's own origin, so
 * only same-origin listeners can read them.
 */

(function () {
    'use strict';

    const MSG_TYPE_TOKEN = 'SUNOSYNC_TOKEN';
    const MSG_TYPE_REFRESH = 'SUNOSYNC_REFRESH';
    const MSG_TYPE_STATUS = 'SUNOSYNC_STATUS';

    // Tags messages as coming from this script instance. The page can read this
    // out of the DOM, so it is a provenance hint rather than a secret; its job
    // is to stop unrelated postMessage traffic being mistaken for ours.
    const CHANNEL = (document.currentScript && document.currentScript.dataset.sunosyncChannel) || '';

    const TARGET_ORIGIN = window.location.origin;

    function post(payload) {
        window.postMessage({ ...payload, channel: CHANNEL }, TARGET_ORIGIN);
    }

    /**
     * Wait for window.Clerk to be available, then grab the token.
     * Clerk may take a moment to initialise after page load.
     */
    function waitForClerk(callback, maxAttempts = 30, interval = 1000) {
        let attempts = 0;

        function check() {
            attempts++;

            if (window.Clerk && window.Clerk.session) {
                callback(null, window.Clerk);
                return;
            }

            if (attempts >= maxAttempts) {
                callback(new Error('Clerk not found after ' + maxAttempts + ' attempts'), null);
                return;
            }

            setTimeout(check, interval);
        }

        check();
    }

    /**
     * Grab the current Clerk session token and hand it to the content script.
     */
    async function grabToken() {
        try {
            if (!window.Clerk || !window.Clerk.session) {
                post({
                    type: MSG_TYPE_STATUS,
                    status: 'no_session',
                    message: 'No Clerk session found. Are you logged in?'
                });
                return;
            }

            const token = await window.Clerk.session.getToken();

            if (token) {
                post({ type: MSG_TYPE_TOKEN, token: token, timestamp: Date.now() });
            } else {
                post({
                    type: MSG_TYPE_STATUS,
                    status: 'no_token',
                    message: 'Clerk session exists but getToken() returned null. Try refreshing the page.'
                });
            }
        } catch (err) {
            post({
                type: MSG_TYPE_STATUS,
                status: 'error',
                message: 'Error getting token: ' + err.message
            });
        }
    }

    // Listen for refresh requests from the content script.
    window.addEventListener('message', function (event) {
        if (event.source !== window) return;
        if (event.origin !== TARGET_ORIGIN) return;
        const data = event.data;
        if (!data || data.type !== MSG_TYPE_REFRESH) return;
        if (CHANNEL && data.channel !== CHANNEL) return;
        grabToken();
    });

    // Initial token grab once Clerk is ready.
    waitForClerk(function (err) {
        if (err) {
            post({
                type: MSG_TYPE_STATUS,
                status: 'clerk_not_found',
                message: err.message
            });
            return;
        }

        // Small delay to ensure the session is fully initialised.
        setTimeout(grabToken, 500);
    });
})();
