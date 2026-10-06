/* Tameio mock runtime: page bar, direction/mode switcher, status bars, tab bars, icons. */
(function () {
  var PAGES = [
    ["index.html", "Brief"],
    ["access-home.html", "Home & Activity"],
    ["composer.html", "Add & Scan"],
    ["plan.html", "Bills & Budgets"],
    ["cash-pantry.html", "Cash & Pantry"],
    ["insights-settings.html", "Insights & Settings"],
    ["desktop.html", "Desktop"]
  ];
  var DIRS = [["calm", "Calm"], ["vault", "Vault"], ["pocket", "Pocket"]];
  var MODES = [["light", "Light"], ["dark", "Dark"]];

  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  var root = document.body;
  var hash = (location.hash || "").slice(1);
  var dir = ["calm", "vault", "pocket"].indexOf(hash) > -1 ? hash : (load("tameio.dir") || root.getAttribute("data-dir") || "calm");
  var sysDark = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
  var rootTheme = document.documentElement.getAttribute("data-theme");
  var mode = load("tameio.mode") || rootTheme || (dir === "vault" ? "dark" : (sysDark ? "dark" : "light"));

  function apply() {
    document.body.setAttribute("data-picked", dir);
    document.querySelectorAll("[data-stage]").forEach(function (el) {
      if (el.hasAttribute("data-fixed-dir")) { el.setAttribute("data-mode", mode); return; }
      el.setAttribute("data-dir", dir); el.setAttribute("data-mode", mode);
    });
    document.querySelectorAll(".switch [data-dir-btn]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-dir-btn") === dir)); });
    document.querySelectorAll(".switch [data-mode-btn]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-mode-btn") === mode)); });
  }

  /* Page bar */
  var bar = document.querySelector(".mock-bar");
  if (bar) {
    var here = location.pathname.split("/").pop() || "index.html";
    var nav = PAGES.map(function (p) {
      return '<a href="' + p[0] + '"' + (p[0] === here ? ' aria-current="page"' : "") + ">" + p[1] + "</a>";
    }).join("");
    bar.innerHTML =
      '<div class="brand"><b>Tameio</b><span>redesign mocks · sample data</span></div>' +
      '<nav class="mock-nav" aria-label="Mock pages">' + nav + "</nav>" +
      '<div class="switch">' +
        '<div class="seg" role="group" aria-label="Direction">' + DIRS.map(function (d) { return '<button type="button" data-dir-btn="' + d[0] + '">' + d[1] + "</button>"; }).join("") + "</div>" +
        '<div class="seg" role="group" aria-label="Mode">' + MODES.map(function (m) { return '<button type="button" data-mode-btn="' + m[0] + '">' + m[1] + "</button>"; }).join("") + "</div>" +
      "</div>";
    bar.addEventListener("click", function (e) {
      var d = e.target.closest("[data-dir-btn]"), m = e.target.closest("[data-mode-btn]");
      if (d) { dir = d.getAttribute("data-dir-btn"); save("tameio.dir", dir); apply(); }
      if (m) { mode = m.getAttribute("data-mode-btn"); save("tameio.mode", mode); apply(); }
    });
  }

  /* Status bar on every phone screen (skip with data-nosb) */
  document.querySelectorAll(".phone .screen").forEach(function (s) {
    if (s.hasAttribute("data-nosb") || s.querySelector(".sb")) return;
    var sb = document.createElement("div");
    sb.className = "sb";
    sb.innerHTML = '<span>9:41</span><span class="sys"><i class="sig"></i><i class="bat"></i></span>';
    s.insertBefore(sb, s.firstChild);
  });

  /* Tab bars: <nav class="tabbar" data-tab="home|activity|plan|insights"></nav> */
  var TABS = [["home", "Home", "house"], ["activity", "Activity", "list"], ["add", "", "plus"], ["plan", "Plan", "calendar-range"], ["insights", "Insights", "chart-pie"]];
  document.querySelectorAll(".tabbar[data-tab]").forEach(function (t) {
    var on = t.getAttribute("data-tab");
    t.innerHTML = TABS.map(function (x) {
      if (x[0] === "add") return '<a class="fab" aria-label="Add"><i data-lucide="plus"></i></a>';
      return '<a class="' + (x[0] === on ? "on" : "") + '"><i data-lucide="' + x[2] + '"></i>' + x[1] + "</a>";
    }).join("");
  });

  apply();
  if (window.lucide) window.lucide.createIcons();
})();
