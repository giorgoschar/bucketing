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

// Failed htmx requests used to fail silently (e.g. a 403 from a form the user
// may not submit). Show the server's `detail` in a small dismissing banner.
// textContent only: the message can echo user input, so it is never HTML.
(function () {
  if (window.__libHtmxErrorInstalled) return;
  window.__libHtmxErrorInstalled = true;

  var timer = null;
  function show(message) {
    var box = document.getElementById('htmx-error-toast');
    if (!box) {
      box = document.createElement('div');
      box.id = 'htmx-error-toast';
      box.setAttribute('role', 'alert');
      box.className = 'fixed bottom-20 left-1/2 -translate-x-1/2 z-50 max-w-sm w-[calc(100%-2rem)] px-4 py-3 ' +
        'rounded-xl bg-red-600 text-white text-sm shadow-lg';
      document.body.appendChild(box);
    }
    box.textContent = message;
    box.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(function () { box.hidden = true; }, 6000);
  }

  document.addEventListener('htmx:responseError', function (evt) {
    var xhr = evt.detail && evt.detail.xhr;
    var status = xhr ? xhr.status : 0;
    var msg = '';
    try {
      var data = JSON.parse(xhr.responseText);
      var detail = data && data.detail;
      if (typeof detail === 'string') msg = detail;
      else if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === 'string') msg = detail[0].msg;
    } catch (_) { /* not JSON */ }
    show(msg || ('Something went wrong (' + status + '). Please try again.'));
  });
})();
