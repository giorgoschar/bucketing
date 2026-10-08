/* Settings › Appearance, before the first paint. A classic script loaded from <head> (index.html): it blocks
   rendering for the few lines below, so a pinned Light or Dark is on <html> before the stylesheet paints the
   page background. main.tsx's bootTheme() runs later, with the app's module code, and is too late for that.

   A plain file: no import. KEY and COLORS must stay equal to THEME_KEY and THEME_COLORS in
   src/shell/theme.ts (src/shell/themeBoot.test.ts checks it). Not inline: the app's CSP is script-src 'self'. */
(function () {
  var KEY = 'tameio.theme'
  var COLORS = { light: '#EEF1F7', dark: '#090B10' }
  var choice = null
  try {
    choice = localStorage.getItem(KEY)
  } catch (e) {
    // Private mode or blocked storage: System.
  }
  var root = document.documentElement
  if (choice !== 'light' && choice !== 'dark') {
    root.removeAttribute('data-theme') // System: tokens.css follows prefers-color-scheme
    return
  }
  root.setAttribute('data-theme', choice)
  // The status bar: index.html has one theme-color per OS scheme; a pinned theme sets both.
  var metas = document.querySelectorAll('meta[name="theme-color"]')
  for (var i = 0; i < metas.length; i++) metas[i].setAttribute('content', COLORS[choice])
})()
