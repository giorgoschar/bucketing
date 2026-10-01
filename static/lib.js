// Shared, framework-free helpers (window.app + the delegated confirm guard). Loaded in <head> so it survives hx-boost
// body swaps; every listener is delegated on document and registered once.
//
// data-confirm="message" on any element (usually a <form> or a button):
// the click/submit is cancelled unless the user confirms. The message travels
// in an HTML attribute, so server-side autoescaping makes user-supplied names
// safe -- never build confirm('...') strings out of template variables.
(function () {
  if (window.__libConfirmInstalled) return;
  window.__libConfirmInstalled = true;

  function guard(event) {
    var el = event.target && event.target.closest
      ? event.target.closest('[data-confirm]') : null;
    if (!el) return;
    // A click on a submit button inside a data-confirm form is covered by the
    // form's own submit event; handle clicks only for non-form carriers.
    if (event.type === 'click' && el.tagName === 'FORM') return;
    if (event.type === 'submit' && el.tagName !== 'FORM') return;
    if (!window.confirm(el.dataset.confirm)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }

  document.addEventListener('click', guard, true);
  document.addEventListener('submit', guard, true);
})();

// window.app: the one place that knows how to talk to the server.
//
//   app.csrfToken()               current CSRF token, read from the cookie.
//   app.fetchJSON(url, opts)      fetch with X-CSRF-Token + JSON headers.
//
// The token comes from the cookie, not the <meta> tag: the tag is rendered once
// at page load, while the server refreshes the cookie mid-session.
//
// fetchJSON resolves with the parsed JSON body (null for an empty or non-JSON
// body) and REJECTS with an Error on any non-2xx response, carrying
// `error.status` and `error.data` (the parsed body, if any), so callers have
// one failure path rather than checking resp.ok separately.
(function () {
  function csrfToken() {
    var m = document.cookie.split('; ').find(function (r) {
      return r.indexOf('csrf_token=') === 0;
    });
    return m ? m.split('=').slice(1).join('=') : '';
  }

  async function fetchJSON(url, opts) {
    opts = opts || {};
    var method = (opts.method || 'GET').toUpperCase();
    var headers = Object.assign({ 'Accept': 'application/json' }, opts.headers || {});
    var init = { method: method, headers: headers, credentials: 'same-origin' };
    if (method !== 'GET' && method !== 'HEAD') {
      headers['X-CSRF-Token'] = csrfToken();
      if (opts.body !== undefined && opts.body !== null) {
        headers['Content-Type'] = 'application/json';
        init.body = typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body);
      }
    }
    var resp = await fetch(url, init);
    var data = null;
    try { data = await resp.json(); } catch (_) { /* empty or non-JSON body */ }
    if (!resp.ok) {
      var msg = data && (data.detail || data.error);
      var err = new Error(typeof msg === 'string' ? msg : 'Request failed (' + resp.status + ')');
      err.status = resp.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  window.app = Object.assign(window.app || {}, { csrfToken: csrfToken, fetchJSON: fetchJSON });
})();
