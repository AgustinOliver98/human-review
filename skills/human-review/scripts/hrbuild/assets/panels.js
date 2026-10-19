// A rebuild, swapped in place: only the tabs that changed, and the reader keeps their place.
//
// The served page reloaded itself whole whenever the build rewrote `.human-review/` — a ↻
// on one tab re-derived that tab and then dropped the reader at the top of a fresh page,
// every fold shut, the note they were typing gone. The build now also writes the page cut
// along its tabs (`hrbuild/shared/panels.py`): `tabs/<id>.html` per tab and `tabs/tabs.json`,
// the manifest, which the server hands over with every watch answer. Every panel on this
// page carries the hash it was built with (`data-hr-hash`), and `<html>` the hash of
// everything that is not a tab (`data-hr-shell`), so the comparison needs nothing else.
//
// `HR.catchUp(watch)` is what server.js's watcher calls when the stamp moves. It resolves
// once the page shows the new build, and rejects whenever it cannot get there in place —
// then the watcher reloads, exactly as before:
//
//   * the manifest is missing, or about another page — a build from before the pieces;
//   * the shell moved: the head, a stylesheet, a script, the masthead, the footer, the set
//     of actions the server offers — anything every tab shares;
//   * the tabs are not the same tabs in the same order;
//   * a changed tab runs an inline script that has not said how to survive a swap
//     (`swappable: false` in the manifest, with the script that blocked it);
//   * a piece on disk is not the one the manifest names — a fetch that raced the next build;
//   * anything at all throws on the way, including a module re-wiring the new markup.
//
// The swap itself is one synchronous block, so nothing paints half done: the changed
// panels' contents and their pills on the strip are replaced, the modules re-wire the new
// markup (`hr:swapped`, one per panel, the event a redrawn draw.io card already fires —
// every script that wires markup at load listens for it), and then the reader's state is put
// back: open <details>, typed or toggled fields, sideways-scrolled boxes, focus, and the
// scroll position, anchored on what was at the top of the screen rather than on a pixel
// offset that the new content may have moved.
(function () {
  var HR = window.HR;
  if (!HR) return;
  var ROOT = document.documentElement;

  function page() {
    try { return decodeURIComponent(location.pathname.split('/').pop() || ''); }
    catch (e) { return ''; }
  }

  // The tab panels, in order: sections carrying a hash, not nested in another panel.
  function livePanels() {
    return [].filter.call(document.querySelectorAll('section.panel[data-hr-hash]'),
      function (p) { return !(p.parentElement && p.parentElement.closest('section.panel')); });
  }

  function refuse(why) { var e = new Error(why); e.panels = true; throw e; }

  // ---- where an element is, in terms that survive the swap ---------------------------
  //
  // The nearest id above it, then the path of steps down from there: the tag, the name a
  // row is known by when it has one (`IDENT` — a sentence's `data-s`, a test's `data-id`),
  // and the index among the siblings that share both. The new markup is the same build's
  // output for nearly the same content, so an element that is still there is found again
  // under the same key even when rows were added above it; one that is not resolves to the
  // closest ancestor that is (`find(..., true)`).
  var IDENT = ['data-s', 'data-id', 'data-cx', 'data-fixture', 'data-find', 'data-level',
               'data-go', 'data-tab', 'data-cat', 'data-ch'];
  function ident(n) {
    for (var i = 0; i < IDENT.length; i++) {
      if (n.hasAttribute(IDENT[i])) return IDENT[i] + '=' + n.getAttribute(IDENT[i]);
    }
    return '';
  }
  function same(a, b) { return a.tagName === b.tagName && ident(a) === ident(b); }
  function keyOf(el, root) {
    var steps = [];
    for (var n = el; n && n !== root; n = n.parentElement) {
      if (n.id) { steps.unshift('#' + n.id); return steps; }
      var i = 0, s = n;
      while ((s = s.previousElementSibling)) if (same(s, n)) i++;
      steps.unshift(n.tagName + '|' + ident(n) + '|' + i);
    }
    return n === root ? steps : null;
  }

  function find(root, steps, nearest) {
    if (!steps) return null;
    var n = root, i = 0;
    if (steps.length && steps[0].charAt(0) === '#') {
      var id = steps[0].slice(1);
      n = root.id === id ? root
        : root.querySelector('[id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
      i = 1;
      if (!n) return nearest ? root : null;
    }
    for (; i < steps.length; i++) {
      var part = steps[i].split('|'), tag = part[0], id = part[1], k = +part[2];
      var hit = null, c = n.firstElementChild;
      for (; c; c = c.nextElementSibling) {
        if (c.tagName === tag && ident(c) === id && k-- === 0) { hit = c; break; }
      }
      if (!hit) return nearest ? n : null;
      n = hit;
    }
    return n;
  }

  // ---- the reader's state in a panel about to be replaced ----------------------------
  //
  // What a control says about itself — a picked sentence (`aria-current`), a pressed
  // toggle (`aria-pressed`), an opened chapter or row (`aria-expanded`) — is put back by
  // pressing it, not by writing the attribute: the press is what opens the chapter, draws
  // the wires, fills the source. Never a control that runs or copies something.
  var PRESSABLE = '[aria-current="true"], [aria-pressed], [aria-expanded]';
  var NEVER = 'a[href]:not([href="#"]), [data-rerun], [data-action], [data-push], [data-dry],'
    + ' .copycmd, .cmd-run, .cmd-copy, [disabled], [aria-disabled="true"]';
  function capture(root) {
    var st = {details: [], fields: [], scrolls: [], focus: null, aria: []};
    [].forEach.call(root.querySelectorAll(PRESSABLE), function (el) {
      if (el.matches(NEVER) || el.tagName === 'DETAILS') return;
      var cur = el.getAttribute('aria-current') === 'true';
      st.aria.push([keyOf(el, root), cur ? 'aria-current' : el.hasAttribute('aria-pressed')
        ? 'aria-pressed' : 'aria-expanded', cur ? 'true' : el.getAttribute(
          el.hasAttribute('aria-pressed') ? 'aria-pressed' : 'aria-expanded')]);
    });
    [].forEach.call(root.querySelectorAll('details'), function (d) {
      st.details.push([keyOf(d, root), d.open]);
    });
    [].forEach.call(root.querySelectorAll('input, textarea, select'), function (f) {
      var k = keyOf(f, root);
      if (f.type === 'checkbox' || f.type === 'radio') {
        if (f.checked !== f.defaultChecked) st.fields.push([k, 'checked', f.checked]);
      } else if (f.tagName === 'SELECT') {
        var changed = [].some.call(f.options, function (o) { return o.selected !== o.defaultSelected; });
        if (changed) st.fields.push([k, 'value', f.value]);
      } else if (f.type !== 'file' && f.value !== f.defaultValue) {
        st.fields.push([k, 'value', f.value]);
      }
    });
    // Only on screen: a hidden panel has no layout, so nothing in it is scrolled.
    if (!root.hidden) {
      [].forEach.call(root.querySelectorAll('*'), function (el) {
        if (el.scrollTop || el.scrollLeft) st.scrolls.push([keyOf(el, root), el.scrollTop, el.scrollLeft]);
      });
    }
    var a = document.activeElement;
    if (a && a !== document.body && root.contains(a)) st.focus = keyOf(a, root);
    return st;
  }

  function restore(root, st) {
    st.details.forEach(function (d) {
      var el = find(root, d[0]);
      if (el && el.tagName === 'DETAILS' && el.open !== d[1]) el.open = d[1];
    });
    st.fields.forEach(function (f) {
      var el = find(root, f[0]);
      if (!el || !(f[1] in el) || el[f[1]] === f[2]) return;
      el[f[1]] = f[2];
      // Through the page's own handlers, so what a box toggles follows the box.
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
    });
    // The pick first — picking a sentence folds the rows shut — then every toggle in page
    // order, each pressed only if it does not already say what it said.
    var picks = st.aria.filter(function (a) { return a[1] === 'aria-current'; });
    var rest = st.aria.filter(function (a) { return a[1] !== 'aria-current'; });
    picks.concat(rest).forEach(function (a) {
      var el = find(root, a[0]);
      if (!el || el.matches(NEVER)) return;
      var now = a[1] === 'aria-current' ? (el.getAttribute('aria-current') === 'true' ? 'true' : '')
        : el.getAttribute(a[1]);
      if (now !== a[2]) el.click();
    });
    st.scrolls.forEach(function (s) {
      var el = find(root, s[0]);
      if (!el) return;
      el.scrollTop = s[1];
      el.scrollLeft = s[2];
    });
    if (st.focus) {
      var f = find(root, st.focus);
      if (f && f.focus) { try { f.focus({preventScroll: true}); } catch (e) {} }
    }
  }

  // ---- the scroll position, by what the reader was looking at ------------------------
  //
  // The element at the top of the readable area (under the pinned masthead), and how far
  // from the top it sat. After the swap the page is scrolled so that it sits there again:
  // the element itself when it is outside every swapped panel, its counterpart by key — or
  // the closest ancestor that survived — when it was inside one.
  function pinned() {
    return parseFloat(getComputedStyle(ROOT).getPropertyValue('--strip-h')) || 0;
  }

  function anchorNow(swapped) {
    var x = Math.round(window.innerWidth / 2), y = Math.min(window.innerHeight - 1, pinned() + 12);
    // The topmost thing in the page's flow at that point, not something pinned over it —
    // the frozen sequence heads (`#seqheads`), a tooltip: everything stacked there is
    // listed, and the first one with no fixed box around it is what the reader is reading.
    var stack = document.elementsFromPoint ? document.elementsFromPoint(x, y) : [document.elementFromPoint(x, y)];
    var el = null;
    for (var s = 0; s < stack.length && !el; s++) {
      var fixed = false;
      for (var n = stack[s]; n && n !== document.body; n = n.parentElement) {
        if (getComputedStyle(n).position === 'fixed') { fixed = true; break; }
      }
      if (!fixed) el = stack[s];
    }
    if (!el || el === document.body || el === ROOT) return null;
    var top = el.getBoundingClientRect().top;
    for (var i = 0; i < swapped.length; i++) {
      if (swapped[i].contains(el)) return {root: swapped[i], key: keyOf(el, swapped[i]), top: top};
    }
    return {el: el, top: top};
  }

  function settleScroll(a) {
    if (!a) return;
    var el = a.el && a.el.isConnected ? a.el : a.root ? find(a.root, a.key, true) : null;
    if (!el) return;
    var delta = el.getBoundingClientRect().top - a.top;
    if (Math.abs(delta) >= 1) {
      window.scrollTo({top: window.pageYOffset + delta, left: window.pageXOffset, behavior: 'instant'});
    }
  }

  // ---- fetching the pieces -----------------------------------------------------------
  function scripts(root, how) {
    return [].map.call(root.querySelectorAll('script[data-hr-swap="' + how + '"]'),
                       function (s) { return (s.getAttribute('src') || '') + '\n' + s.textContent; });
  }

  function fetchPiece(t, live) {
    return fetch('tabs/' + encodeURIComponent(t.id) + '.html', {cache: 'no-store'})
      .then(function (r) {
        if (!r.ok) refuse('tabs/' + t.id + '.html: ' + r.status);
        return r.text();
      })
      .then(function (text) {
        var nl = text.indexOf('\n');
        // A piece from a build other than the manifest's: the next build started under us.
        if (text.slice(0, nl) !== '<!-- hr-tab ' + t.id + ' ' + t.hash + ' -->') {
          refuse('tabs/' + t.id + '.html is not the build the manifest names');
        }
        var box = document.createElement('template');
        box.innerHTML = text.slice(nl + 1);
        var sec = box.content.firstElementChild;
        if (!sec || sec.tagName !== 'SECTION' || sec.id !== t.id
            || sec.getAttribute('data-hr-hash') !== t.hash) refuse('tabs/' + t.id + '.html is malformed');
        var pillBox = document.createElement('template');
        pillBox.innerHTML = t.pill || '';
        var pill = pillBox.content.firstElementChild;
        if (!pill || pill.id !== 'tabbtn-' + t.id) refuse('the manifest\'s pill for ' + t.id + ' is malformed');
        // A `keep` script is not re-run: the listeners it registered at load serve the new
        // markup. That holds only for the same code — a changed one has to be loaded fresh.
        var had = scripts(live, 'keep');
        scripts(sec, 'keep').forEach(function (code) {
          if (had.indexOf(code) < 0) refuse(t.id + ': a data-hr-swap="keep" script changed');
        });
        return {t: t, live: live, sec: sec, pill: pill};
      });
  }

  // ---- the swap ----------------------------------------------------------------------
  function swap(pieces) {
    // Whatever floats over the old markup — a tooltip, a sequence arrow's detail, a popup
    // — is anchored to nodes about to go. Every one of them closes on Escape.
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    var roots = pieces.map(function (p) { return p.live; });
    var anchor = anchorNow(roots);
    var states = pieces.map(function (p) { return capture(p.live); });

    // A module that throws while wiring the new markup reports it to `window` and carries
    // on; caught here, it fails the whole swap, and the page reloads rather than stay
    // half-wired.
    var failed = null;
    function trap(ev) { if (!failed) failed = ev.error || new Error(ev.message || 'script error'); }
    window.addEventListener('error', trap);
    try {
      pieces.forEach(function (p) {
        var live = p.live;
        // The section itself stays: the strip holds it, and so does whatever listens for
        // the panel showing or hiding. Only its contents and its hash are the new build's.
        var fresh = document.createDocumentFragment();
        while (p.sec.firstChild) fresh.appendChild(p.sec.firstChild);
        live.textContent = '';
        live.appendChild(fresh);
        live.setAttribute('data-hr-hash', p.sec.getAttribute('data-hr-hash'));
        live.className = p.sec.className;
        var pill = document.getElementById('tabbtn-' + p.t.id);
        if (pill) {
          var regen = pill.classList.contains('tab-regen');
          pill.innerHTML = p.pill.innerHTML;
          pill.className = p.pill.className;
          if (regen) pill.classList.add('tab-regen');
          if (p.pill.hasAttribute('aria-label')) pill.setAttribute('aria-label', p.pill.getAttribute('aria-label'));
          else pill.removeAttribute('aria-label');
        }
        // A `rerun` script wires what it finds and is safe to run again: it runs, over the
        // new panel, the way it ran over the old one at load.
        [].forEach.call(live.querySelectorAll('script[data-hr-swap="rerun"]'), function (old) {
          var run = document.createElement('script');
          [].forEach.call(old.attributes, function (a) { run.setAttribute(a.name, a.value); });
          run.textContent = old.textContent;
          old.parentNode.replaceChild(run, old);
        });
      });
      pieces.forEach(function (p) {
        document.dispatchEvent(new CustomEvent('hr:swapped', {detail: p.live}));
      });
    } finally {
      window.removeEventListener('error', trap);
    }
    if (failed) throw failed;
    pieces.forEach(function (p, i) { restore(p.live, states[i]); });
    settleScroll(anchor);
  }

  function catchUp(w) {
    return Promise.resolve().then(function () {
      var m = w && w.panels;
      if (!m || m.version !== 1) refuse('no tab manifest');
      if (m.page !== page()) refuse('the manifest is about ' + m.page + ', not ' + page());
      if (!m.shell || m.shell !== ROOT.getAttribute('data-hr-shell')) refuse('the shell changed');
      var live = livePanels();
      var ids = live.map(function (p) { return p.id; }).join(' ');
      if ((m.tabs || []).map(function (t) { return t.id; }).join(' ') !== ids) refuse('the tabs changed');
      var changed = [];
      m.tabs.forEach(function (t, i) {
        if (t.hash !== live[i].getAttribute('data-hr-hash')) changed.push({t: t, live: live[i]});
      });
      if (!changed.length) { said('nothing on the page changed', []); return 'same'; }
      changed.forEach(function (c) {
        if (!c.t.swappable) {
          refuse(c.t.id + ' runs a script that cannot be re-run in place: '
                 + (c.t.blockers || []).join(' | '));
        }
      });
      return Promise.all(changed.map(function (c) { return fetchPiece(c.t, c.live); }))
        .then(function (pieces) {
          swap(pieces);
          said('swapped in place', pieces.map(function (p) { return p.t.id; }));
          return 'swapped';
        });
    }).catch(function (e) {
      said('reloading: ' + (e && e.message || e), []);
      throw e;
    });
  }

  // What the last catch-up did, for whoever is asking (the console, a test). Kept across
  // the reload it may end in, so a reload can say why it happened.
  var LAST = 'hr-panels-last:' + location.pathname;
  function said(how, tabs) {
    HR.lastCatchUp = {how: how, tabs: tabs, at: Date.now()};
    try { sessionStorage.setItem(LAST, JSON.stringify(HR.lastCatchUp)); } catch (e) {}
    if (window.console && console.info) console.info('[human-review] ' + how + (tabs.length ? ': ' + tabs.join(', ') : ''));
  }
  try { HR.lastCatchUp = JSON.parse(sessionStorage.getItem(LAST) || 'null'); } catch (e) {}

  HR.catchUp = catchUp;
})();
