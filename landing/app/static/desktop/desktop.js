/*
 * desktop.js — glue for the SUS vintage-Macintosh desktop.
 *
 * Wires the static DOM (menu bar + desktop icons) to the two modules:
 *   - window.WM          (wm.js)          — draggable windows
 *   - window.ContextMenu (contextmenu.js) — right-click & menu-bar popups
 *
 * Responsibilities: menu-bar clock, Apple/File/View dropdowns, icon
 * selection, double-click to open (folders, apps, New App), right-click
 * context menus (Open / Build / History), a "Find" search over all apps,
 * a light/dark appearance toggle, and the first-run Setup alert.
 */
(function () {
  "use strict";

  // --- small helpers -------------------------------------------------------

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function data() {
    try { return JSON.parse($("#desktop-data").textContent) || {}; }
    catch (e) { return {}; }
  }

  function safeKey(s) { return String(s || "").replace(/[^a-zA-Z0-9_-]/g, "_"); }

  // --- appearance (light / dark / system) ---------------------------------

  function setTheme(mode) {
    var root = document.documentElement;
    if (mode === "system") { root.removeAttribute("data-theme"); }
    else { root.setAttribute("data-theme", mode); }
    try { localStorage.setItem("sus-theme", mode); } catch (e) {}
    applyThemeToFrames();
  }

  function initTheme() {
    var mode = null;
    try { mode = localStorage.getItem("sus-theme"); } catch (e) {}
    if (mode === "light" || mode === "dark") {
      document.documentElement.setAttribute("data-theme", mode);
    }
    // "system" or null → leave to prefers-color-scheme.
  }

  // --- menu-bar clock ------------------------------------------------------

  function startClock() {
    var el = $("#menubar-clock");
    if (!el) return;
    function tick() {
      var now = new Date();
      var s;
      try {
        s = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      } catch (e) {
        s = now.getHours() + ":" + ("0" + now.getMinutes()).slice(-2);
      }
      el.textContent = s;
    }
    tick();
    setInterval(tick, 15000);
  }

  // --- window openers ------------------------------------------------------

  // Apply the desktop's current appearance to one framed document.
  function setDocTheme(doc) {
    var mode = document.documentElement.getAttribute("data-theme");
    if (mode) doc.documentElement.setAttribute("data-theme", mode);
    else doc.documentElement.removeAttribute("data-theme");
  }

  // Run fn over a framed doc AND its nested same-origin frame. Windows nest one
  // level: run.html -> the app iframe, build.html -> the preview iframe.
  function eachFramedDoc(iframe, fn) {
    try {
      var doc = iframe.contentDocument;
      if (!doc) return;
      fn(doc);
      doc.querySelectorAll("iframe").forEach(function (inner) {
        try { if (inner.contentDocument) fn(inner.contentDocument); } catch (e) {}
      });
    } catch (e) { /* cross-origin — leave it be */ }
  }

  // In the desktop, a window's close box IS "back to catalog" — a platform page
  // that navigates its own frame to "/" would load the whole desktop inside the
  // window (SUS-in-SUS). These pages are same-origin, so once framed we hide
  // their back-to-root nav and mirror the desktop's theme down to the app.
  function neutralizeFrame(iframe) {
    try {
      var doc = iframe.contentDocument;
      if (doc) {
        doc.documentElement.classList.add("sus-embedded");
        doc.querySelectorAll('a[href="/"]').forEach(function (a) { a.style.display = "none"; });
        // The nested app frame may load after this pass — theme it on load too.
        doc.querySelectorAll("iframe").forEach(function (inner) {
          if (inner.__susThemeHooked) return;
          inner.__susThemeHooked = true;
          inner.addEventListener("load", function () {
            try { if (inner.contentDocument) setDocTheme(inner.contentDocument); } catch (e) {}
          });
        });
      }
    } catch (e) { /* cross-origin — leave it be */ }
    eachFramedDoc(iframe, setDocTheme);
  }

  // Propagate the current appearance to every open (same-origin) window, two
  // levels deep so app content inside run/build windows follows the toggle.
  function applyThemeToFrames() {
    $all("#windows .window__body iframe").forEach(function (f) {
      eachFramedDoc(f, setDocTheme);
    });
  }

  // Open a same-origin platform page (run/build/history/setup/…) in a window,
  // then keep its in-page root nav neutralized across reloads.
  function openFramed(opts) {
    if (!window.WM) { window.location.href = opts.url; return null; }
    var win = window.WM.open(opts);
    if (!win) return win;
    var iframe = win.querySelector(".window__body iframe");
    if (iframe) {
      neutralizeFrame(iframe);
      // WM.open de-dupes on id, so guard against stacking a load listener on the
      // same iframe each time an already-open window is re-focused.
      if (!iframe.__susNeutralizeHooked) {
        iframe.__susNeutralizeHooked = true;
        iframe.addEventListener("load", function () { neutralizeFrame(iframe); });
      }
    }
    return win;
  }

  function openUrl(url, title, idHint) {
    openFramed({ id: "win-" + safeKey(idHint || url), title: title || url, url: url });
  }

  function openApp(icon) {
    var name = icon.getAttribute("data-name") || "App";
    var key = safeKey(icon.getAttribute("data-team") + "-" + icon.getAttribute("data-slug"));
    openFramed({ id: "run-" + key, title: name, url: icon.getAttribute("data-run-url") });
  }

  function buildApp(icon) {
    var name = icon.getAttribute("data-name") || "App";
    var key = safeKey(icon.getAttribute("data-team") + "-" + icon.getAttribute("data-slug"));
    openFramed({ id: "build-" + key, title: "Build — " + name, url: icon.getAttribute("data-build-url") });
  }

  function historyApp(icon) {
    var name = icon.getAttribute("data-name") || "App";
    var key = safeKey(icon.getAttribute("data-team") + "-" + icon.getAttribute("data-slug"));
    openFramed({ id: "hist-" + key, title: "History — " + name, url: icon.getAttribute("data-history-url") });
  }

  function openFolder(team) {
    var tpl = document.querySelector('template[data-folder="' + (window.CSS && CSS.escape ? CSS.escape(team) : team) + '"]');
    var content = tpl ? tpl.innerHTML : '<div class="folder-view__empty">This folder is empty.</div>';
    window.WM.open({ id: "folder-" + safeKey(team), title: team, content: content, width: 480, height: 320 });
  }

  function openAbout() {
    var d = data();
    var html =
      '<div class="mac-alert__body" style="text-align:center;padding:1.25rem;">' +
      '<div style="font-size:2.5rem;line-height:1;">🤨</div>' +
      '<p style="margin-top:.5rem;"><strong>Single Use Software</strong></p>' +
      '<p>Welcome, ' + escapeHtml(d.user || "friend") + ".</p>" +
      "</div>";
    window.WM.open({ id: "about", title: "About This Desktop", content: html, width: 300, height: 200 });
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // --- menu-bar dropdowns --------------------------------------------------

  function dropdownBelow(el, items) {
    // ContextMenu treats pointer events on the `owner` as non-dismissing, so
    // while a menu is open its owning title still carries is-open — a second
    // mousedown here toggles it shut. `onHide` clears is-open on every dismissal
    // (mousedown outside, item pick, Escape, scroll, resize). No gesture-spanning
    // state, so nothing can be stranded. Titles are bound to mousedown (wire()).
    if (el.classList.contains("is-open")) { window.ContextMenu.hide(); return; }
    var r = el.getBoundingClientRect();
    el.classList.add("is-open");
    window.ContextMenu.show(r.left, r.bottom, items, {
      owner: el,
      onHide: function () { el.classList.remove("is-open"); }
    });
  }

  function appleMenu(el) {
    dropdownBelow(el, [
      { label: "About This Desktop", action: openAbout },
      { separator: true },
      { label: "New App…", action: function () { openUrl("/new", "New App", "/new"); } },
      { label: "Skills", action: function () { openUrl("/skills", "Skills", "skills"); } },
      { label: "Analytics", action: function () { openUrl("/analytics", "Analytics", "analytics"); } },
      { label: "Setup", action: function () { openUrl("/setup", "Setup", "setup"); } }
    ]);
  }

  function fileMenu(el) {
    dropdownBelow(el, [
      { label: "New App…", action: function () { openUrl("/new", "New App", "/new"); } },
      { separator: true },
      { label: "Find…", action: function () { var s = $("#desktop-search"); if (s) s.focus(); } }
    ]);
  }

  function viewMenu(el) {
    dropdownBelow(el, [
      { label: "About This Desktop", action: openAbout },
      { separator: true },
      { label: "Appearance: Light", action: function () { setTheme("light"); } },
      { label: "Appearance: Dark", action: function () { setTheme("dark"); } },
      { label: "Appearance: System", action: function () { setTheme("system"); } }
    ]);
  }

  // --- selection -----------------------------------------------------------

  function selectOnly(icon) {
    $all(".icon.is-selected").forEach(function (n) { if (n !== icon) n.classList.remove("is-selected"); });
    if (icon) icon.classList.add("is-selected");
  }

  // --- icon context menus --------------------------------------------------

  function appMenu(icon, x, y) {
    window.ContextMenu.show(x, y, [
      { label: "Open", action: function () { openApp(icon); } },
      { separator: true },
      { label: "Build", action: function () { buildApp(icon); } },
      { label: "History", action: function () { historyApp(icon); } }
    ]);
  }

  function folderMenu(team, x, y) {
    window.ContextMenu.show(x, y, [
      { label: "Open", action: function () { openFolder(team); } }
    ]);
  }

  // --- "Find" search over all apps ----------------------------------------

  function allAppIcons() {
    // Clone every app icon out of the per-team templates into one array.
    var out = [];
    $all("template[data-folder]").forEach(function (tpl) {
      $all(".icon--app", tpl.content).forEach(function (node) { out.push(node); });
    });
    return out;
  }

  function runSearch(q) {
    q = (q || "").trim().toLowerCase();
    if (!q) { if (window.WM) window.WM.close("find"); return; }

    var matches = allAppIcons().filter(function (node) {
      var hay = [
        node.getAttribute("data-name"),
        node.getAttribute("data-team"),
        node.getAttribute("data-desc"),
        node.getAttribute("data-tags")
      ].join(" ").toLowerCase();
      return hay.indexOf(q) !== -1;
    });

    var inner;
    if (!matches.length) {
      inner = '<div class="folder-view__empty">No apps match “' + escapeHtml(q) + '”.</div>';
    } else {
      var frag = document.createElement("div");
      frag.className = "folder-view";
      matches.forEach(function (n) { frag.appendChild(n.cloneNode(true)); });
      inner = frag.outerHTML;
    }
    var win = window.WM.open({ id: "find", title: "Find", content: inner, width: 480, height: 300 });
    // WM.open de-dupes on id and ignores `content` when the window already
    // exists, so write into the existing body as the query narrows.
    var body = win && win.querySelector(".window__body");
    if (body) body.innerHTML = inner;
  }

  function debounce(fn, ms) {
    var t;
    return function () { var a = arguments, c = this; clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms); };
  }

  // --- event wiring --------------------------------------------------------

  function wire() {
    // Menu bar. Bound to mousedown so a re-click's toggle runs before
    // ContextMenu's own outside-dismiss on the same gesture (the owner guard
    // keeps the menu open until this handler decides).
    var logo = $("#apple-menu"); if (logo) logo.addEventListener("mousedown", function () { appleMenu(logo); });
    $all(".menubar__menu").forEach(function (m) {
      m.addEventListener("mousedown", function () {
        var which = m.getAttribute("data-menu");
        if (which === "file") fileMenu(m);
        else if (which === "view") viewMenu(m);
      });
    });

    // Search.
    var search = $("#desktop-search");
    if (search) {
      var deb = debounce(function () { runSearch(search.value); }, 180);
      search.addEventListener("input", deb);
      search.addEventListener("search", function () { runSearch(search.value); });
    }

    // Icon interactions via delegation (covers desktop + opened folder/find windows).
    document.addEventListener("click", function (e) {
      var icon = e.target.closest ? e.target.closest(".icon") : null;
      if (icon) { selectOnly(icon); return; }
      // Click on empty space clears selection (but not clicks in the menu bar).
      if (!e.target.closest || !e.target.closest("#menubar, .menu, .window")) selectOnly(null);
    });

    document.addEventListener("dblclick", function (e) {
      var icon = e.target.closest ? e.target.closest(".icon") : null;
      if (!icon) return;
      if (icon.classList.contains("icon--folder")) { openFolder(icon.getAttribute("data-team")); }
      else if (icon.classList.contains("icon--app")) { openApp(icon); }
      else if (icon.hasAttribute("data-open-url")) { openUrl(icon.getAttribute("data-open-url"), icon.getAttribute("data-title") || "SUS", icon.getAttribute("data-open-url")); }
    });

    document.addEventListener("contextmenu", function (e) {
      var icon = e.target.closest ? e.target.closest(".icon") : null;
      if (!icon) return; // let the browser menu appear off-icon
      e.preventDefault();
      selectOnly(icon);
      if (icon.classList.contains("icon--app")) appMenu(icon, e.clientX, e.clientY);
      else if (icon.classList.contains("icon--folder")) folderMenu(icon.getAttribute("data-team"), e.clientX, e.clientY);
    });

    // Enter/Return opens the selected icon (keyboard nicety).
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      var icon = document.activeElement && document.activeElement.closest ? document.activeElement.closest(".icon") : null;
      if (!icon) return;
      if (icon.classList.contains("icon--folder")) openFolder(icon.getAttribute("data-team"));
      else if (icon.classList.contains("icon--app")) openApp(icon);
      else if (icon.hasAttribute("data-open-url")) openUrl(icon.getAttribute("data-open-url"), icon.getAttribute("data-title") || "SUS", icon.getAttribute("data-open-url"));
    });
  }

  // --- first-run setup alert ----------------------------------------------

  function maybeSetupAlert() {
    if (data().setupComplete) return;
    var tpl = $("#setup-alert-tpl");
    if (!tpl || !window.WM) return;
    var win = window.WM.open({ id: "setup-alert", title: "SUS", content: tpl.innerHTML, width: 400, height: 270 });
    // The alert lives in a content window, so its <a href="/setup"> would
    // navigate the whole desktop away. Open Setup in a window instead (keeps the
    // metaphor and gets the same back-nav neutralization as the menus).
    var btn = win && win.querySelector('a[href="/setup"]');
    if (btn) btn.addEventListener("click", function (e) {
      e.preventDefault();
      openUrl("/setup", "Setup", "setup");
    });
  }

  // --- boot ---------------------------------------------------------------

  function boot() {
    initTheme();
    startClock();
    wire();
    maybeSetupAlert();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
