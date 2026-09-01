/*
 * wm.js — Vintage-Macintosh desktop Window Manager
 *
 * A dependency-free, single-file window manager exposed as the global
 * `window.WM`. No libraries, no imports, no build step — drop it in via a
 * plain `<script src="…/wm.js"></script>` tag.
 *
 * Public API (other modules depend on these names — do NOT rename):
 *   WM.open({ id, title, url, content, width, height, x, y }) -> window element
 *   WM.focus(id)
 *   WM.close(id)
 *
 * DOM contract (classes are styled by teammate CSS — do NOT invent new names):
 *   <div class="window is-active" data-window-id="ID" style="…">
 *     <div class="window__titlebar">
 *       <span class="window__close" title="Close"></span>
 *       <div class="window__stripes"></div>
 *       <div class="window__title">TITLE</div>
 *     </div>
 *     <div class="window__body"> …iframe or content… </div>
 *     <div class="window__resize" title="Resize"></div>
 *   </div>
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Configuration / constants
  // ---------------------------------------------------------------------------
  var DEFAULT_WIDTH = 640;
  var DEFAULT_HEIGHT = 440;
  var MIN_WIDTH = 240;
  var MIN_HEIGHT = 120;
  var CASCADE_OFFSET = 24; // px offset between successively cascaded windows
  var BASE_Z = 100; // starting z-index; each focus increments beyond this

  // ---------------------------------------------------------------------------
  // Internal state
  // ---------------------------------------------------------------------------
  // Map of window id -> window DOM element.
  var windows = Object.create(null);
  // Monotonically increasing z-index counter; every focus() bumps this.
  var zCounter = BASE_Z;
  // Id of the currently active (focused) window, or null.
  var activeId = null;
  // Number of windows opened so far, used to compute cascade positions.
  var openCount = 0;

  // ---------------------------------------------------------------------------
  // Layer / geometry helpers
  // ---------------------------------------------------------------------------

  /**
   * Lazily resolve (or create) the `#windows` layer that hosts all windows.
   * Robust to being called before the DOM is fully ready: if `#windows` is
   * missing we create it and attach to `.desktop` (preferred) or `<body>`.
   * Returns null only if there is genuinely nowhere to attach yet.
   */
  function getLayer() {
    var layer = document.getElementById('windows');
    if (layer) return layer;

    // Need a parent to attach a freshly-created layer to.
    var parent = document.querySelector('.desktop') || document.body;
    if (!parent) return null; // DOM not ready enough — caller should retry.

    layer = document.createElement('div');
    layer.id = 'windows';
    parent.appendChild(layer);
    return layer;
  }

  /**
   * Bounding rectangle of the layer in viewport coordinates. This accounts for
   * the desktop layer's offset (e.g. the menu-bar height pushing it down), so
   * pointer math never assumes the layer starts at (0,0).
   * Falls back to a window-sized rect if the layer is unavailable.
   */
  function getLayerRect() {
    var layer = getLayer();
    if (layer && typeof layer.getBoundingClientRect === 'function') {
      var r = layer.getBoundingClientRect();
      // Guard against a zero-sized layer (e.g. display:contents) by falling
      // back to viewport dimensions for width/height.
      return {
        left: r.left,
        top: r.top,
        width: r.width || window.innerWidth || 0,
        height: r.height || window.innerHeight || 0
      };
    }
    return {
      left: 0,
      top: 0,
      width: window.innerWidth || 0,
      height: window.innerHeight || 0
    };
  }

  /** Clamp a number between lo and hi (defensive against inverted bounds). */
  function clamp(value, lo, hi) {
    if (hi < lo) hi = lo;
    if (value < lo) return lo;
    if (value > hi) return hi;
    return value;
  }

  /**
   * Extract client X/Y from a mouse or pointer/touch event uniformly.
   */
  function getPoint(evt) {
    if (typeof evt.clientX === 'number') {
      return { x: evt.clientX, y: evt.clientY };
    }
    if (evt.touches && evt.touches.length) {
      return { x: evt.touches[0].clientX, y: evt.touches[0].clientY };
    }
    return { x: 0, y: 0 };
  }

  // ---------------------------------------------------------------------------
  // Focus / z-order
  // ---------------------------------------------------------------------------

  /**
   * Raise the window with the given id to the top of the stack and mark it
   * active; all other windows lose `.is-active`.
   */
  function focus(id) {
    var el = windows[id];
    if (!el) return;

    // Raise above everything currently on screen.
    zCounter += 1;
    el.style.zIndex = String(zCounter);

    // Toggle active class across all managed windows.
    for (var key in windows) {
      var w = windows[key];
      if (!w) continue;
      if (key === id) {
        w.classList.add('is-active');
      } else {
        w.classList.remove('is-active');
      }
    }
    activeId = id;
  }

  // ---------------------------------------------------------------------------
  // Close
  // ---------------------------------------------------------------------------

  /** Remove the window with the given id from the DOM and internal state. */
  function close(id) {
    var el = windows[id];
    if (!el) return;

    if (el.parentNode) {
      el.parentNode.removeChild(el);
    }
    delete windows[id];

    if (activeId === id) {
      activeId = null;
      // Optionally promote the top-most remaining window to active so the
      // desktop always has a sensible focus target.
      var topId = null;
      var topZ = -Infinity;
      for (var key in windows) {
        var w = windows[key];
        if (!w) continue;
        var z = parseInt(w.style.zIndex, 10) || 0;
        if (z > topZ) {
          topZ = z;
          topId = key;
        }
      }
      if (topId) focus(topId);
    }
  }

  // ---------------------------------------------------------------------------
  // Drag (move via titlebar)
  // ---------------------------------------------------------------------------

  /**
   * Begin dragging a window by its titlebar. Uses document-level listeners for
   * the duration of the drag and cleans them up on release. Clamps so that the
   * title bar always stays within the desktop (layer) bounds.
   */
  function startDrag(el, evt) {
    var rect = getLayerRect();
    var start = getPoint(evt);

    // Window's current position relative to the layer.
    var startLeft = parseFloat(el.style.left) || 0;
    var startTop = parseFloat(el.style.top) || 0;

    var winWidth = el.offsetWidth || DEFAULT_WIDTH;
    // Height of the titlebar — the part we insist stays on-screen.
    var titlebar = el.querySelector('.window__titlebar');
    var barHeight = (titlebar && titlebar.offsetHeight) || 22;

    function onMove(moveEvt) {
      var p = getPoint(moveEvt);
      var dx = p.x - start.x;
      var dy = p.y - start.y;

      var newLeft = startLeft + dx;
      var newTop = startTop + dy;

      // Keep at least the title bar within the desktop bounds. We allow the
      // window to run off the right/bottom a bit but keep the bar grabbable.
      var maxLeft = rect.width - winWidth;
      var maxTop = rect.height - barHeight;
      newLeft = clamp(newLeft, 0, Math.max(0, maxLeft));
      newTop = clamp(newTop, 0, Math.max(0, maxTop));

      el.style.left = newLeft + 'px';
      el.style.top = newTop + 'px';

      if (moveEvt.cancelable) moveEvt.preventDefault();
    }

    function onUp() {
      document.body.classList.remove('is-dragging');
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('mouseup', onUp, true);
      document.removeEventListener('touchmove', onMove, true);
      document.removeEventListener('touchend', onUp, true);
      document.removeEventListener('touchcancel', onUp, true);
      window.removeEventListener('blur', onUp, true);
    }

    // Shield iframes (pointer-events:none via CSS) so mousemove keeps reaching
    // the parent document for the whole gesture instead of being swallowed the
    // instant the cursor crosses a window's iframe body.
    document.body.classList.add('is-dragging');
    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('mouseup', onUp, true);
    document.addEventListener('touchmove', onMove, { capture: true, passive: false });
    document.addEventListener('touchend', onUp, true);
    document.addEventListener('touchcancel', onUp, true);
    // Belt-and-braces: if a mouseup is lost (pointer left the window, or a
    // context menu opened mid-gesture), window blur ends the gesture so
    // .is-dragging can't stick and leave every window's iframe click-dead.
    window.addEventListener('blur', onUp, true);

    if (evt.cancelable) evt.preventDefault();
  }

  // ---------------------------------------------------------------------------
  // Resize (via corner grip)
  // ---------------------------------------------------------------------------

  /**
   * Begin resizing a window by its `.window__resize` grip. Enforces sane
   * minimums and cleans up its document-level listeners on release.
   */
  function startResize(el, evt) {
    var start = getPoint(evt);
    var startWidth = el.offsetWidth || DEFAULT_WIDTH;
    var startHeight = el.offsetHeight || DEFAULT_HEIGHT;

    // A window resizes from its fixed top-left corner, so cap width/height at
    // the desktop edge — otherwise the overflow-hidden desktop clips the
    // window and its off-screen resize grip becomes unclickable. Hoisted out
    // of onMove (left/top don't change during a resize).
    var layer = getLayerRect();
    var elLeft = parseFloat(el.style.left) || 0;
    var elTop = parseFloat(el.style.top) || 0;

    function onMove(moveEvt) {
      var p = getPoint(moveEvt);
      var newWidth = startWidth + (p.x - start.x);
      var newHeight = startHeight + (p.y - start.y);

      newWidth = clamp(newWidth, MIN_WIDTH, Math.max(MIN_WIDTH, layer.width - elLeft));
      newHeight = clamp(newHeight, MIN_HEIGHT, Math.max(MIN_HEIGHT, layer.height - elTop));

      el.style.width = newWidth + 'px';
      el.style.height = newHeight + 'px';

      if (moveEvt.cancelable) moveEvt.preventDefault();
    }

    function onUp() {
      document.body.classList.remove('is-dragging');
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('mouseup', onUp, true);
      document.removeEventListener('touchmove', onMove, true);
      document.removeEventListener('touchend', onUp, true);
      document.removeEventListener('touchcancel', onUp, true);
      window.removeEventListener('blur', onUp, true);
    }

    // Shield iframes (pointer-events:none via CSS) so mousemove keeps reaching
    // the parent document for the whole gesture instead of being swallowed the
    // instant the cursor crosses a window's iframe body.
    document.body.classList.add('is-dragging');
    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('mouseup', onUp, true);
    document.addEventListener('touchmove', onMove, { capture: true, passive: false });
    document.addEventListener('touchend', onUp, true);
    document.addEventListener('touchcancel', onUp, true);
    // Belt-and-braces: if a mouseup is lost (pointer left the window, or a
    // context menu opened mid-gesture), window blur ends the gesture so
    // .is-dragging can't stick and leave every window's iframe click-dead.
    window.addEventListener('blur', onUp, true);

    if (evt.cancelable) evt.preventDefault();
  }

  // ---------------------------------------------------------------------------
  // Window construction
  // ---------------------------------------------------------------------------

  /**
   * Compute a cascade position for a new window, keeping it inside the desktop.
   */
  function cascadePosition(width, height) {
    var rect = getLayerRect();
    var offset = (openCount * CASCADE_OFFSET) % Math.max(1, (Math.min(rect.width, rect.height) || 1));

    // A small base inset so windows don't hug the very corner.
    var base = 16;
    var x = base + offset;
    var y = base + offset;

    // Keep fully within the desktop where possible.
    var maxX = Math.max(0, rect.width - width);
    var maxY = Math.max(0, rect.height - height);
    x = clamp(x, 0, maxX);
    y = clamp(y, 0, maxY);

    return { x: x, y: y };
  }

  /**
   * Build the window DOM element per the DOM contract and wire up behaviors.
   */
  function buildWindow(opts) {
    var id = opts.id;
    var title = opts.title != null ? String(opts.title) : '';
    var width = typeof opts.width === 'number' ? opts.width : DEFAULT_WIDTH;
    var height = typeof opts.height === 'number' ? opts.height : DEFAULT_HEIGHT;

    width = Math.max(MIN_WIDTH, width);
    height = Math.max(MIN_HEIGHT, height);

    // Position: explicit x/y, else cascade.
    var pos;
    if (typeof opts.x === 'number' && typeof opts.y === 'number') {
      pos = { x: opts.x, y: opts.y };
    } else {
      pos = cascadePosition(width, height);
    }

    // --- Root window element -------------------------------------------------
    var el = document.createElement('div');
    el.className = 'window is-active';
    el.setAttribute('data-window-id', id);
    el.style.position = 'absolute';
    el.style.left = pos.x + 'px';
    el.style.top = pos.y + 'px';
    el.style.width = width + 'px';
    el.style.height = height + 'px';
    el.style.zIndex = String(zCounter + 1); // focus() below finalizes ordering

    // --- Titlebar ------------------------------------------------------------
    var titlebar = document.createElement('div');
    titlebar.className = 'window__titlebar';

    var closeBtn = document.createElement('span');
    closeBtn.className = 'window__close';
    closeBtn.setAttribute('title', 'Close');

    var stripes = document.createElement('div');
    stripes.className = 'window__stripes';

    var titleEl = document.createElement('div');
    titleEl.className = 'window__title';
    titleEl.textContent = title;

    titlebar.appendChild(closeBtn);
    titlebar.appendChild(stripes);
    titlebar.appendChild(titleEl);

    // --- Body ----------------------------------------------------------------
    var body = document.createElement('div');
    body.className = 'window__body';

    if (opts.url) {
      // url wins over content: host an iframe filling the body.
      var iframe = document.createElement('iframe');
      iframe.setAttribute('src', String(opts.url));
      iframe.style.width = '100%';
      iframe.style.height = '100%';
      iframe.style.border = '0';
      iframe.setAttribute('frameborder', '0');
      body.appendChild(iframe);
    } else if (opts.content != null) {
      body.innerHTML = String(opts.content);
    }

    // --- Resize grip ---------------------------------------------------------
    var resize = document.createElement('div');
    resize.className = 'window__resize';
    resize.setAttribute('title', 'Resize');

    // --- Assemble ------------------------------------------------------------
    el.appendChild(titlebar);
    el.appendChild(body);
    el.appendChild(resize);

    // --- Behaviors -----------------------------------------------------------

    // Focus: any mousedown/touchstart on the window raises it.
    el.addEventListener('mousedown', function () {
      focus(id);
    }, false);
    el.addEventListener('touchstart', function () {
      focus(id);
    }, false);

    // Close button.
    closeBtn.addEventListener('mousedown', function (evt) {
      // Prevent this from initiating a drag or other titlebar handling.
      evt.stopPropagation();
    }, false);
    closeBtn.addEventListener('click', function (evt) {
      evt.stopPropagation();
      close(id);
    }, false);

    // Drag via titlebar (but not when starting on the close box).
    titlebar.addEventListener('mousedown', function (evt) {
      if (evt.target && evt.target.classList &&
          evt.target.classList.contains('window__close')) {
        return; // don't start a drag from the close box
      }
      focus(id);
      startDrag(el, evt);
    }, false);
    titlebar.addEventListener('touchstart', function (evt) {
      if (evt.target && evt.target.classList &&
          evt.target.classList.contains('window__close')) {
        return;
      }
      focus(id);
      startDrag(el, evt);
    }, false);

    // Window-shade: double-click the titlebar collapses/expands the body.
    titlebar.addEventListener('dblclick', function (evt) {
      if (evt.target && evt.target.classList &&
          evt.target.classList.contains('window__close')) {
        return;
      }
      el.classList.toggle('is-collapsed');
    }, false);

    // Resize via corner grip.
    resize.addEventListener('mousedown', function (evt) {
      evt.stopPropagation(); // don't let this bubble into drag handling
      focus(id);
      startResize(el, evt);
    }, false);
    resize.addEventListener('touchstart', function (evt) {
      evt.stopPropagation();
      focus(id);
      startResize(el, evt);
    }, false);

    return el;
  }

  // ---------------------------------------------------------------------------
  // Public: open
  // ---------------------------------------------------------------------------

  /**
   * Open (or focus an existing) window. Returns the window element, or null if
   * called with an invalid id or before there is anywhere to attach it.
   */
  function open(opts) {
    opts = opts || {};
    if (opts.id == null || opts.id === '') {
      // id is required and used as the unique key.
      if (window.console && console.warn) {
        console.warn('WM.open: missing required "id".');
      }
      return null;
    }
    var id = String(opts.id);

    // De-dupe: if it already exists, just focus and return it.
    if (windows[id]) {
      focus(id);
      return windows[id];
    }

    var layer = getLayer();
    if (!layer) {
      if (window.console && console.warn) {
        console.warn('WM.open: no #windows layer / desktop / body to attach to yet.');
      }
      return null;
    }

    var el = buildWindow({
      id: id,
      title: opts.title,
      url: opts.url,
      content: opts.content,
      width: opts.width,
      height: opts.height,
      x: opts.x,
      y: opts.y
    });

    windows[id] = el;
    openCount += 1;
    layer.appendChild(el);

    // Finalize z-order and active state.
    focus(id);

    return el;
  }

  // Clicking inside a background window whose body is an <iframe> focuses the
  // iframe, not the parent, so no mousedown reaches our per-window handler and
  // the window never raises. Detect it: when the parent loses focus to an
  // iframe, raise the window that iframe belongs to.
  window.addEventListener('blur', function () {
    setTimeout(function () {
      var ae = document.activeElement;
      if (!ae || ae.tagName !== 'IFRAME' || !ae.closest) return;
      var win = ae.closest('.window');
      if (!win) return;
      var wid = win.getAttribute('data-window-id');
      if (wid && windows[wid] && wid !== activeId) focus(wid);
    }, 0);
  }, false);

  // ---------------------------------------------------------------------------
  // Expose global API
  // ---------------------------------------------------------------------------
  window.WM = {
    open: open,
    focus: focus,
    close: close
  };
})();
