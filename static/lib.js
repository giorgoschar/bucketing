// Shared, framework-free helpers. Loaded in <head> so it survives hx-boost
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
