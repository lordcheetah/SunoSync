/**
 * SunoSync Token Helper — Background Service Worker / Event Page
 *
 * Receives tokens from the content script, pushes them to the SunoSync desktop
 * app over the local bridge, and manages the refresh timer.
 *
 * Runs unmodified on Chrome (MV3 service worker) and Firefox/Zen (MV3 event
 * page). Only the manifest differs between the two.
 */

/**
 * Namespace shim. Firefox exposes the promise-based `browser` namespace; its
 * `chrome` alias is callback-based, so `await chrome.storage.local.get(...)`
 * resolves to undefined there and every await in this file silently produced
 * garbage — which is why pairing never worked in Firefox/Zen. Chrome MV3's
 * `chrome` namespace is already promise-based, so preferring `browser` when
 * present gives one promise API on both.
 */
const api = (typeof globalThis.browser !== 'undefined' && globalThis.browser.runtime)
    ? globalThis.browser
    : globalThis.chrome;

const TOKEN_SERVER_URL = 'http://127.0.0.1:38945';
const AUTH_HEADER = 'X-SunoSync-Auth';
const ALARM_NAME = 'sunosync_token_refresh';
const POLL_ALARM_NAME = 'sunosync_app_poll';

// Firefox MV3 does not grant host permissions at install time, so the bridge is
// unreachable until the user grants them. The popup requests these on pairing.
const REQUIRED_ORIGINS = [
    'https://suno.com/*',
    'https://*.suno.com/*',
    'http://127.0.0.1:38945/*'
];

/**
 * Chrome and Firefox both clamp alarms to a 30 second floor. The previous
 * version asked for 5 second polling and 6 second refreshes and silently got
 * 30 seconds instead, which meant the "token is about to expire, refresh now"
 * path fired *after* the token had already lapsed. We now work with the floor
 * rather than against it: the alarm is a durable safety net, and setTimeout
 * covers sub-30s refreshes while the worker is alive.
 */
const ALARM_FLOOR_MINUTES = 0.5;
const REFRESH_LEAD_SECONDS = 15;   // Refresh this long before expiry.
const FALLBACK_REFRESH_SECONDS = 45;

// --- State ---
let state = {
    lastToken: null,
    lastRefresh: null,
    appConnected: false,
    sunoLoggedIn: false,
    paired: false,
    lastError: null
};

let shortTimer = null;

// --- Persist & Load State ---
function saveState() {
    // The session JWT is deliberately NOT persisted. It lives for about a
    // minute, and writing it to extension storage left a copy on disk long
    // after it stopped being useful.
    const { lastToken, ...persistable } = state;
    return api.storage.local.set({ sunosync_state: persistable });
}

async function loadState() {
    try {
        const result = await api.storage.local.get(['sunosync_state', 'pairing_secret']);
        if (result.sunosync_state) {
            state = { ...state, ...result.sunosync_state, lastToken: state.lastToken };
        }
        state.paired = Boolean(result.pairing_secret);
    } catch (err) {
        console.error('[SunoSync] Could not load state:', err);
    }
}

async function getPairingSecret() {
    try {
        const { pairing_secret } = await api.storage.local.get('pairing_secret');
        return pairing_secret || null;
    } catch {
        return null;
    }
}

// --- Host permissions ---
/**
 * Whether the extension may actually reach suno.com and the local bridge.
 *
 * Chrome grants `host_permissions` at install time, so this is always true
 * there. Firefox MV3 treats them as opt-in: until the user grants them, fetch()
 * to 127.0.0.1 fails and tabs.query() with a url filter returns nothing, with
 * no error that distinguishes it from "the app isn't running".
 */
async function hasHostPermissions() {
    try {
        return await api.permissions.contains({ origins: REQUIRED_ORIGINS });
    } catch {
        // permissions API unavailable — assume the manifest grant applies.
        return true;
    }
}

// --- JWT Helpers ---
function parseJwt(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(function (c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        return null;
    }
}

// --- Talk to the desktop app ---
async function bridgeFetch(path, options = {}) {
    const secret = await getPairingSecret();
    if (!secret) {
        state.paired = false;
        state.lastError = 'Not paired. Copy the pairing code from SunoSync → Settings.';
        throw new Error('unpaired');
    }
    state.paired = true;

    return fetch(TOKEN_SERVER_URL + path, {
        ...options,
        headers: {
            ...(options.headers || {}),
            [AUTH_HEADER]: secret
        }
    });
}

async function pushTokenToApp(token) {
    try {
        const response = await bridgeFetch('/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token }),
            signal: AbortSignal.timeout(5000)
        });

        if (response.ok) {
            state.appConnected = true;
            state.lastError = null;
            await saveState();
            updateBadge('connected');
            scheduleSmartRefresh(token);
            return true;
        }

        state.appConnected = response.status !== 401;
        state.lastError = response.status === 401
            ? 'Pairing code rejected. Re-copy it from SunoSync → Settings.'
            : 'App returned HTTP ' + response.status;
        await saveState();
        updateBadge('error');
        return false;
    } catch (err) {
        state.appConnected = false;
        if (err.message !== 'unpaired') {
            state.lastError = 'Cannot reach SunoSync. Is the app running?';
        }
        await saveState();
        updateBadge(state.paired ? 'disconnected' : 'error');
        return false;
    }
}

// --- Scheduling ---
function scheduleSmartRefresh(token) {
    let refreshInSeconds = FALLBACK_REFRESH_SECONDS;

    const claims = token ? parseJwt(token) : null;
    if (claims && claims.exp) {
        const timeToExpiry = claims.exp - Math.floor(Date.now() / 1000);
        refreshInSeconds = Math.max(5, timeToExpiry - REFRESH_LEAD_SECONDS);
        console.log(`[SunoSync] Token expires in ${timeToExpiry}s; refreshing in ${refreshInSeconds}s.`);
    }

    // Short-horizon refresh via setTimeout, which is not subject to the alarm
    // floor. Only valid while the worker stays alive.
    if (shortTimer) clearTimeout(shortTimer);
    if (refreshInSeconds < 30) {
        shortTimer = setTimeout(requestTokenRefresh, refreshInSeconds * 1000);
    }

    // Alarm as the durable backstop; survives worker suspension.
    api.alarms.create(ALARM_NAME, {
        delayInMinutes: Math.max(ALARM_FLOOR_MINUTES, refreshInSeconds / 60)
    });
}

function ensurePollAlarm() {
    api.alarms.create(POLL_ALARM_NAME, { periodInMinutes: ALARM_FLOOR_MINUTES });
}

// --- Check if the app is running ---
async function checkAppStatus() {
    const wasConnected = state.appConnected;
    try {
        const response = await bridgeFetch('/status', {
            method: 'GET',
            signal: AbortSignal.timeout(3000)
        });

        if (response.ok) {
            state.appConnected = true;
            state.lastError = null;
            if (!wasConnected && state.lastToken) {
                console.log('[SunoSync] App discovered; pushing cached token.');
                pushTokenToApp(state.lastToken);
            }
        } else {
            state.appConnected = false;
            if (response.status === 401) {
                state.lastError = 'Pairing code rejected. Re-copy it from SunoSync → Settings.';
            }
        }
    } catch (err) {
        state.appConnected = false;
        if (err.message === 'unpaired') {
            updateBadge('error');
            await saveState();
            return;
        }
    }
    await saveState();
    updateBadge(state.appConnected ? 'connected' : 'disconnected');
}

// --- Badge ---
function updateBadge(status) {
    const colors = {
        connected: '#10b981',
        disconnected: '#6b7280',
        error: '#ef4444'
    };
    const texts = {
        connected: '✓',
        disconnected: '',
        error: '!'
    };

    api.action.setBadgeBackgroundColor({ color: colors[status] || '#6b7280' });
    api.action.setBadgeText({ text: texts[status] || '' });
}

// --- Ask the suno.com tab for a fresh token ---
async function requestTokenRefresh() {
    try {
        const tabs = await api.tabs.query({
            url: ['https://suno.com/*', 'https://*.suno.com/*']
        });

        if (tabs.length === 0) {
            state.sunoLoggedIn = false;
            state.lastError = 'No suno.com tab open';
            await saveState();
            return;
        }

        for (const tab of tabs) {
            try {
                await api.tabs.sendMessage(tab.id, { action: 'refresh_token' });
                return;
            } catch {
                continue; // Content script not loaded in that tab yet.
            }
        }
    } catch (err) {
        console.error('[SunoSync] Error requesting refresh:', err);
    }
}

// --- Messages ---
api.runtime.onMessage.addListener((message, sender, sendResponse) => {
    // Only trust messages originating from this extension's own pages and
    // content scripts, never from a web page.
    if (!sender || sender.id !== api.runtime.id) {
        return false;
    }

    if (message.action === 'token_received') {
        state.lastToken = message.token;
        state.lastRefresh = Date.now();
        state.sunoLoggedIn = true;
        saveState();
        pushTokenToApp(message.token).then((success) => sendResponse({ success }));
        return true;
    }

    if (message.action === 'status_update') {
        if (message.status === 'no_session' || message.status === 'clerk_not_found') {
            state.sunoLoggedIn = false;
        }
        state.lastError = message.message;
        saveState();
        return false;
    }

    if (message.action === 'get_state') {
        hasHostPermissions().then((granted) => {
            const { lastToken, ...safe } = state;
            sendResponse({ ...safe, hostPermissions: granted });
        });
        return true;
    }

    if (message.action === 'manual_refresh') {
        requestTokenRefresh();
        sendResponse({ ok: true });
        return false;
    }

    if (message.action === 'set_pairing_secret') {
        (async () => {
            await api.storage.local.set({ pairing_secret: message.secret });
            state.paired = Boolean(message.secret);
            state.lastError = null;
            await checkAppStatus();
            const granted = await hasHostPermissions();
            if (!granted) {
                state.lastError =
                    'Permission to reach SunoSync has not been granted. Use "Grant access" above.';
            }
            const { lastToken, ...safe } = state;
            sendResponse({ ...safe, hostPermissions: granted });
        })();
        return true;
    }

    if (message.action === 'check_app') {
        (async () => {
            const granted = await hasHostPermissions();
            if (granted) {
                await checkAppStatus();
            } else {
                state.appConnected = false;
                state.lastError =
                    'Permission to reach SunoSync has not been granted. Use "Grant access" above.';
                updateBadge('error');
            }
            const { lastToken, ...safe } = state;
            sendResponse({ ...safe, hostPermissions: granted });
        })();
        return true;
    }

    return false;
});

// --- Alarms ---
api.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === ALARM_NAME) {
        requestTokenRefresh();
    } else if (alarm.name === POLL_ALARM_NAME) {
        checkAppStatus();
    }
});

// --- Lifecycle ---
async function bootstrap() {
    await loadState();
    ensurePollAlarm();
    checkAppStatus();
}

api.runtime.onInstalled.addListener(bootstrap);
api.runtime.onStartup.addListener(bootstrap);

// MV3 workers restart on demand, so re-hydrate on every wake-up too.
bootstrap();
