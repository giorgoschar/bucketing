/*
 * Alpine components used by the shared layout.
 *
 * Loaded from <head>, before alpine.min.js, for the same reason as
 * insights.js and expense-wizard.js: hx-boost swaps the <body>, and HTMX
 * inserts the fragment before evaluating any <script> inside it, so a factory
 * defined in the body does not exist when Alpine initialises the incoming
 * nodes.
 *
 * Keeping these in the body forced base.html to re-run Alpine.initTree() on
 * htmx:afterSettle to catch what Alpine had missed — which re-initialised
 * trees Alpine had already claimed and made it throw "Cannot convert undefined
 * or null to object" from its teardown on every navigation.
 */

function notifCenter() {
      return {
        open: false,
        unread: 0,
        items: [],
        hasMore: false,
        offset: 0,
        _timer: null,
        async init() {
          await this.fetchNotifs(0);
          /* hx-boost swaps the <body> on every navigation, so this component
             re-initialises each time. setInterval lives on window, not the DOM,
             so the previous timer survived the swap and kept polling — after a
             few tab changes the app was firing several /notifications requests
             a minute and climbing. Keep exactly one, on window. */
          if (window.__notifTimer) clearInterval(window.__notifTimer);
          window.__notifTimer = setInterval(() => this.fetchNotifs(0, true), 60000);
          this._timer = window.__notifTimer;
        },

        destroy() {
          if (window.__notifTimer) {
            clearInterval(window.__notifTimer);
            window.__notifTimer = null;
          }
        },
        async fetchNotifs(offset = 0, silent = false) {
          /* Two bells exist (desktop sidebar + mobile bar) and both re-init on
             every hx-boost swap, so an uncached fetch here cost several
             /notifications requests per tab change. Share one recent result
             across components and navigations; the 60s poller and any explicit
             open still refresh it. */
          if (offset === 0 && !silent && window.__notifCache &&
              Date.now() - window.__notifCache.at < 20000) {
            const d = window.__notifCache.data;
            this.unread = d.unread; this.items = d.items;
            this.hasMore = d.has_more; this.offset = d.offset;
            return;
          }
          try {
            const r = await fetch(`/notifications?offset=${offset}`, { headers: { 'Accept': 'application/json' } });
            if (!r.ok) return;
            const d = await r.json();
            if (offset === 0) window.__notifCache = { at: Date.now(), data: d };
            this.unread = d.unread;
            this.hasMore = d.has_more;
            this.offset = offset;
            if (offset === 0 || silent) {
              this.items = d.items || [];
            } else {
              this.items = [...this.items, ...(d.items || [])];
            }
          } catch (_) {}
        },
        async loadMore() {
          await this.fetchNotifs(this.offset + 50);
        },
        async markAllRead() {
          try {
            await fetch('/notifications/read-all', { method: 'POST', headers: { 'X-CSRF-Token': _csrfToken() } });
            this.unread = 0;
            this.items  = this.items.map(n => ({ ...n, is_read: true }));
          } catch (_) {}
        },
        relativeTime(iso) {
          if (!iso) return '';
          const diff = (Date.now() - new Date(iso).getTime()) / 1000;
          if (diff < 60)   return 'just now';
          if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
          if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
          return Math.floor(diff / 86400) + 'd ago';
        },
      };
    }

function pushSettings() {
    return {
      subStatus: 'pending',
      statusText: 'Checking\u2026',
      loading: false,
      feedback: '',
      feedbackOk: true,
      _sub: null,

      async init() {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
          this.subStatus = 'unsupported';
          this.statusText = 'Push notifications are not supported in this browser.';
          return;
        }
        try {
          const reg = await navigator.serviceWorker.ready;
          this._sub = await reg.pushManager.getSubscription();
          if (this._sub) {
            this.subStatus = 'subscribed';
            this.statusText = 'This device will receive push notifications.';
          } else {
            this.subStatus = 'none';
            this.statusText = 'Push notifications are not enabled on this device.';
          }
        } catch (e) {
          this.subStatus = 'none';
          this.statusText = 'Could not determine subscription status.';
        }
      },

      async subscribe() {
        this.loading = true;
        this.feedback = '';
        try {
          const reg = await navigator.serviceWorker.ready;
          const keyResp = await fetch('/push/vapid-public-key');
          if (!keyResp.ok) { this._err('VAPID keys are not configured on the server.'); return; }
          const { public_key } = await keyResp.json();
          const permission = await Notification.requestPermission();
          if (permission !== 'granted') { this._err('Permission denied. Please allow notifications in browser settings.'); return; }
          const sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: this._urlB64(public_key),
          });
          await fetch('/push/subscribe', { method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()}, body: JSON.stringify(sub) });
          this._sub = sub;
          this.subStatus = 'subscribed';
          this.statusText = 'This device will receive push notifications.';
          this._ok('Subscribed! You will now receive push notifications.');
        } catch (e) {
          this._err('Failed to subscribe: ' + e.message);
        } finally {
          this.loading = false;
        }
      },

      async unsubscribe() {
        this.loading = true;
        this.feedback = '';
        try {
          if (this._sub) {
            await fetch('/push/subscribe', { method: 'DELETE', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()}, body: JSON.stringify({ endpoint: this._sub.endpoint }) });
            await this._sub.unsubscribe();
            this._sub = null;
          }
          this.subStatus = 'none';
          this.statusText = 'Push notifications are not enabled on this device.';
          this._ok('Unsubscribed from push notifications.');
        } catch (e) {
          this._err('Failed to unsubscribe: ' + e.message);
        } finally {
          this.loading = false;
        }
      },

      async sendTest() {
        this.loading = true;
        this.feedback = '';
        try {
          const resp = await fetch('/push/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken() },
            body: JSON.stringify({ endpoint: this._sub?.endpoint || null }),
          });
          const data = await resp.json();
          if (data.sent) {
            this._ok('Test notification sent! Check your device.');
          } else {
            this._err(data.error || 'Push delivery failed.');
          }
        } catch (e) {
          this._err('Request failed: ' + e.message);
        } finally {
          this.loading = false;
        }
      },

      _ok(msg) { this.feedback = msg; this.feedbackOk = true; },
      _err(msg) { this.feedback = msg; this.feedbackOk = false; },

      _urlB64(b64) {
        const pad = '='.repeat((4 - b64.length % 4) % 4);
        const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
        return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
      },
    };
  }
