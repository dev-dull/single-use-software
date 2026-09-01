/*
 * contextmenu.js — classic-Macintosh popup menus.
 *
 * Used for BOTH right-click context menus on desktop icons AND menu-bar
 * dropdowns. Vanilla JS, no libraries, no imports. Exposes a single global:
 *
 *   window.ContextMenu.show(x, y, items, opts?)   // opts: { owner, onHide }
 *   window.ContextMenu.hide()
 *
 * `items` entries are either:
 *   { label, action, disabled? }  — clickable row (runs action() then hides)
 *   { separator: true }           — divider row
 *
 * DOM contract (classes styled by teammate CSS — do not rename):
 *   <div class="menu">
 *     <div class="menu__item">…</div>
 *     <div class="menu__item menu__item--disabled">…</div>
 *     <div class="menu__sep"></div>
 *   </div>
 */
(function () {
  'use strict';

  // The one menu element currently on screen (or null).
  var current = null;
  // Optional owner element (the control that toggles this menu) and an onHide
  // callback, both supplied via show()'s opts. A pointer event on the owner is
  // not an "outside" dismissal — the owner's own handler decides (toggle).
  var owner = null;
  var onHideCb = null;

  // Guards against the very mousedown that opened the menu immediately
  // dismissing it (the caller may still be inside that event's bubble).
  var listenersAttached = false;

  function onOutsidePointer(e) {
    if (!current) {
      return;
    }
    // A pointer event inside the menu is handled by the item click handler;
    // ignore it here so we don't tear the menu down before the action fires.
    if (current.contains(e.target)) {
      return;
    }
    // The owner's own handler decides what its pointer event means (toggle), so
    // don't treat it as an outside dismissal.
    if (owner && owner.contains(e.target)) {
      return;
    }
    hide();
  }

  function onKeyDown(e) {
    if (e.key === 'Escape' || e.keyCode === 27) {
      hide();
    }
  }

  function onScrollOrResize() {
    hide();
  }

  function attachListeners() {
    if (listenersAttached) {
      return;
    }
    // Use capture so we see the event before it can be stopped elsewhere.
    document.addEventListener('mousedown', onOutsidePointer, true);
    document.addEventListener('click', onOutsidePointer, true);
    document.addEventListener('keydown', onKeyDown, true);
    // `true` for scroll captures scrolling on nested elements too.
    window.addEventListener('scroll', onScrollOrResize, true);
    window.addEventListener('resize', onScrollOrResize, false);
    listenersAttached = true;
  }

  function detachListeners() {
    if (!listenersAttached) {
      return;
    }
    document.removeEventListener('mousedown', onOutsidePointer, true);
    document.removeEventListener('click', onOutsidePointer, true);
    document.removeEventListener('keydown', onKeyDown, true);
    window.removeEventListener('scroll', onScrollOrResize, true);
    window.removeEventListener('resize', onScrollOrResize, false);
    listenersAttached = false;
  }

  function hide() {
    // Snapshot + clear the callback before teardown so it runs at most once and
    // can safely open a new menu.
    var cb = onHideCb;
    owner = null;
    onHideCb = null;
    if (current) {
      if (current.parentNode) {
        current.parentNode.removeChild(current);
      }
      current = null;
    }
    detachListeners();
    if (typeof cb === 'function') {
      cb();
    }
  }

  function buildItem(item) {
    if (item && item.separator) {
      var sep = document.createElement('div');
      sep.className = 'menu__sep';
      return sep;
    }

    var row = document.createElement('div');
    row.className = 'menu__item';
    var disabled = !!(item && item.disabled);
    if (disabled) {
      row.className += ' menu__item--disabled';
    }
    row.textContent = item && item.label != null ? String(item.label) : '';

    row.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (disabled) {
        return;
      }
      var action = item && item.action;
      // Hide first so the action can itself open a new menu if it wants.
      hide();
      if (typeof action === 'function') {
        action();
      }
    });

    return row;
  }

  function show(x, y, items, opts) {
    // Always replace any existing menu (this fires the previous menu's onHide).
    hide();

    // Robust against no/empty items: show nothing.
    if (!items || !items.length) {
      return;
    }

    owner = (opts && opts.owner) || null;
    onHideCb = (opts && typeof opts.onHide === 'function') ? opts.onHide : null;

    var menu = document.createElement('div');
    menu.className = 'menu';
    menu.style.position = 'absolute';
    menu.style.zIndex = '2147483647';
    // Position off-screen for measurement without a visible flash.
    menu.style.left = '0px';
    menu.style.top = '0px';
    menu.style.visibility = 'hidden';

    // Right-clicking the menu itself should not open the native menu.
    menu.addEventListener('contextmenu', function (e) {
      e.preventDefault();
    });

    for (var i = 0; i < items.length; i++) {
      menu.appendChild(buildItem(items[i]));
    }

    document.body.appendChild(menu);
    current = menu;
    attachListeners();

    // Flip/clamp so the menu stays within the viewport.
    var vw = document.documentElement.clientWidth || window.innerWidth || 0;
    var vh = document.documentElement.clientHeight || window.innerHeight || 0;
    var rect = menu.getBoundingClientRect();
    var w = rect.width;
    var h = rect.height;

    var left = x;
    var top = y;

    // Overflow right -> shift left so the right edge fits.
    if (left + w > vw) {
      left = vw - w;
    }
    // Overflow bottom -> shift up so the bottom edge fits.
    if (top + h > vh) {
      top = vh - h;
    }
    // Never go past the top-left corner.
    if (left < 0) {
      left = 0;
    }
    if (top < 0) {
      top = 0;
    }

    // Account for page scroll since we position absolutely on the document.
    var scrollX = window.pageXOffset || document.documentElement.scrollLeft || 0;
    var scrollY = window.pageYOffset || document.documentElement.scrollTop || 0;

    menu.style.left = (left + scrollX) + 'px';
    menu.style.top = (top + scrollY) + 'px';
    menu.style.visibility = 'visible';
  }

  window.ContextMenu = {
    show: show,
    hide: hide
  };
})();
