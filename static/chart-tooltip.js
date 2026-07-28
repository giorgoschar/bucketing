/*
 * Tooltips for the server-rendered SVG charts.
 *
 * The charts previously relied on SVG <title>, which the browser shows as a
 * native tooltip: about a second of delay, no styling, and nothing at all on a
 * phone — where this app is mostly used. This replaces it with a single
 * delegated listener on document.
 *
 * Delegation is the point. The charts live inside #insights-body, which HTMX
 * replaces wholesale on every filter change, and base.html swaps the whole
 * <body> on navigation. A listener bound to the chart elements would have to be
 * rebound after each swap — the leak that made navigation slow down. One
 * listener on document, registered once, survives every swap and never
 * accumulates.
 *
 * Markup contract: any element carrying data-tip="..." gets a tooltip on
 * hover, tap and keyboard focus.
 */
(function () {
  if (window.__chartTipWired) return;
  window.__chartTipWired = true;

  var node = null;
  var active = null;

  function el() {
    // isConnected, not just a null check: hx-boost replaces the whole <body>,
    // which takes this element with it. The variable still pointed at the
    // detached node, so after any in-app navigation the tooltip was being
    // written to an element that was no longer in the document.
    if (!node || !node.isConnected) {
      node = document.createElement('div');
      node.className = 'chart-tip';
      node.setAttribute('role', 'tooltip');
      document.body.appendChild(node);
    }
    return node;
  }

  function place(target, clientX, clientY) {
    var tip = el();
    var box = tip.getBoundingClientRect();
    var margin = 8;

    // Anchor above the pointer, or above the element itself for keyboard focus
    // where there are no pointer coordinates.
    var x = clientX;
    var y = clientY;
    if (x == null || y == null) {
      var r = target.getBoundingClientRect();
      x = r.left + r.width / 2;
      y = r.top;
    }

    var left = x - box.width / 2;
    var top = y - box.height - margin;

    // Keep it on screen: a point at the left or right edge of a chart would
    // otherwise push the tooltip out of the viewport.
    left = Math.max(margin, Math.min(left, window.innerWidth - box.width - margin));
    if (top < margin) top = y + margin;   // flip below when there is no room above

    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }

  function show(target, clientX, clientY) {
    var text = target.getAttribute('data-tip');
    if (!text) return;
    var tip = el();
    if (active !== target) {
      tip.textContent = text;
      active = target;
    }
    tip.setAttribute('data-show', '1');
    place(target, clientX, clientY);
  }

  function hide() {
    active = null;
    if (node) node.removeAttribute('data-show');
  }

  function targetOf(e) {
    var t = e.target;
    // SVG shapes support closest(), but text nodes and the document do not.
    return t && t.closest ? t.closest('[data-tip]') : null;
  }

  document.addEventListener('pointerover', function (e) {
    var t = targetOf(e);
    if (t) show(t, e.clientX, e.clientY);
  });

  document.addEventListener('pointermove', function (e) {
    var t = targetOf(e);
    if (t) show(t, e.clientX, e.clientY);
    else if (active) hide();
  });

  document.addEventListener('pointerout', function (e) {
    if (targetOf(e) && !targetOf({ target: e.relatedTarget })) hide();
  });

  // Touch: there is no hover, so a tap has to both open and close.
  document.addEventListener('pointerdown', function (e) {
    var t = targetOf(e);
    if (t) show(t, e.clientX, e.clientY);
    else hide();
  });

  document.addEventListener('focusin', function (e) {
    var t = targetOf(e);
    if (t) show(t, null, null);
    else hide();
  });

  document.addEventListener('focusout', hide);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') hide();
  });

  // Scrolling moves the anchor out from under a fixed-position tooltip, so it
  // has to follow — not vanish. Hiding on scroll looked right until a chart
  // below the fold was hovered: the browser smooth-scrolls it into view and
  // those scroll events kept arriving after the pointer had settled, closing
  // the tooltip the moment it opened.
  document.addEventListener('scroll', function () {
    if (!active) return;
    if (!active.isConnected) return hide();
    place(active, null, null);
  }, true);

  // A tooltip left over from the previous page would hang in mid-air. HTMX
  // events bubble to document, which matters here: this file is loaded from
  // <head>, so document.body does not exist yet at registration time.
  document.addEventListener('htmx:beforeSwap', hide);
})();
