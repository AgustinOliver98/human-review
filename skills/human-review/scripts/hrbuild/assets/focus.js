// The focus chooser: every level is already in the page, so switching is a visibility
// flip, not a fetch — the guide must keep working as a single emailed file.
// Wired at load and again over whatever a rebuild swaps in (`hr:swapped`), once per bar.
(function () {
  function wire(root) {
  root.querySelectorAll('.diagram .focus').forEach(function (bar) {
    if (bar.__hrFocus) return;
    bar.__hrFocus = true;
    var diagram = bar.closest('.diagram');
    bar.addEventListener('click', function (ev) {
      var button = ev.target.closest('button[data-level]');
      if (!button) return;
      var level = button.getAttribute('data-level');
      bar.querySelectorAll('button[data-level]').forEach(function (b) {
        b.setAttribute('aria-pressed', String(b === button));
      });
      diagram.querySelectorAll('.svgbox[data-level]').forEach(function (box) {
        box.hidden = box.getAttribute('data-level') !== level;
      });
    });
  });
  }
  wire(document);
  document.addEventListener('hr:swapped', function (ev) {
    var root = ev.detail;
    if (root && root.querySelectorAll) wire(root);
  });
})();


// The morph between two renders of one diagram. A picture that switches to another render
// of itself — a wider radius, or any card's Diff / New / Old — comes back
// with its own layout, so a bare visibility flip throws every box somewhere new and the
// reader loses the change they were looking at. Instead: slide every box both renders
// share from its old spot to its new one, ghost out the ones that left, and fade the
// newcomers in with a short glow — what appeared is the thing the switch exists to show.
// Edges are re-routed by every render, so they are not tracked: they fade in once the
// boxes have landed.
//
// Two triggers, one animation. The radius chooser (PlantUML) runs in the capture phase,
// ahead of the chooser above, and performs the same flip itself so the order of the two
// listeners never matters; it also scrolls so the changed (ripple-1) boxes stay where
// the eye already is. The Diff / New / Old switch (dgm-views.js) is watched instead of
// intercepted: its `data-state` changes, and the morph reads the pane it left by
// un-hiding it for one synchronous measurement — before the browser paints anything.
(function () {
  if (window.__dgmMorph) return;
  window.__dgmMorph = true;
  var MOVE = 380, GLOW = 1400;
  var motion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var CELL = 'g[data-cell-id]';

  function svgOf(box) { return box && box.querySelector('svg'); }
  function isDrawio(svg) { return !!(svg && svg.querySelector(CELL)); }

  // A draw.io cell's own marks: what it draws itself, not what the cells nested in it draw.
  function own(g, sel) {
    return Array.prototype.filter.call(g.querySelectorAll(sel), function (el) {
      return el.closest(CELL) === g;
    });
  }
  // An edge is the one cell whose line takes the pointer by its stroke; its labels are
  // cells nested inside it; a layer (and the root) draws nothing of its own.
  function cellKind(g) {
    var mine = own(g, 'rect, path, ellipse, polygon, polyline, line, image, text, foreignObject');
    if (!mine.length) return '';
    if (mine.some(function (el) { return el.getAttribute('pointer-events') === 'stroke'; })) return 'edge';
    var up = g.parentNode && g.parentNode.closest ? g.parentNode.closest(CELL) : null;
    return up && cellKind(up) === 'edge' ? 'label' : 'vertex';
  }
  function label(g) {
    return own(g, 'foreignObject, text').map(function (el) { return el.textContent; })
      .join(' ').replace(/\s+/g, ' ').trim();
  }

  // The boxes of one picture, keyed so the same box can be found in another render of
  // it: a PlantUML entity by its qualified name, a draw.io vertex by its cell id.
  function entities(svg) {
    var out = {};
    if (!svg) return out;
    if (isDrawio(svg)) {
      svg.querySelectorAll(CELL).forEach(function (g) {
        if (cellKind(g) === 'vertex') out[g.getAttribute('data-cell-id')] = g;
      });
      return out;
    }
    svg.querySelectorAll('g.entity[data-qualified-name]').forEach(function (g) {
      out[g.getAttribute('data-qualified-name')] = g;
    });
    return out;
  }
  // Everything that is not a box — edges, title, legend — waits for the boxes.
  function waiting(svg) {
    if (isDrawio(svg)) {
      return Array.prototype.filter.call(svg.querySelectorAll(CELL), function (g) {
        return cellKind(g) === 'edge';
      });
    }
    return Array.prototype.slice.call(
      svg.querySelectorAll('g.link, g.title, g.footer, g.caption, g.legend, g.cluster'));
  }
  // A PlantUML picture the morph can key: boxes by qualified name. A sequence diagram's
  // participants carry the name too, but are not `g.entity`, and are left to a plain flip.
  function hasBoxes(svg) { return !!(svg && !isDrawio(svg) && svg.querySelector('g.entity[data-qualified-name]')); }
  function text(g) { return (g.textContent || '').replace(/\s+/g, ' ').trim(); }
  // A PlantUML line keyed by the names of the two boxes it joins (its own ids are per
  // render), counted so two lines between one pair stay two.
  function links(svg) {
    var names = {}, out = {};
    svg.querySelectorAll('g.entity[id][data-qualified-name]').forEach(function (g) {
      names[g.id] = g.getAttribute('data-qualified-name');
    });
    svg.querySelectorAll('g.link[data-entity-1][data-entity-2]').forEach(function (g) {
      var a = names[g.getAttribute('data-entity-1')], b = names[g.getAttribute('data-entity-2')];
      if (!a || !b) return;
      var key = a + '>' + b + ':' + (g.getAttribute('data-link-type') || ''), n = 0;
      while ((key + '#' + n) in out) n++;
      out[key + '#' + n] = { g: g, ends: [a, b] };
    });
    return out;
  }
  // New key -> old key. By key first; then, on a draw.io picture, by label for the boxes
  // a redraw handed a new id — only where the label names exactly one box on each side.
  function match(oldEnt, newEnt, byLabel) {
    var pairs = {}, taken = {};
    Object.keys(newEnt).forEach(function (n) { if (n in oldEnt) { pairs[n] = n; taken[n] = true; } });
    if (!byLabel) return pairs;
    function index(ent, skip) {
      var at = {};
      Object.keys(ent).forEach(function (n) {
        if (skip[n]) return;
        var t = label(ent[n]);
        if (t) at[t] = at[t] === undefined ? n : null;
      });
      return at;
    }
    var olds = index(oldEnt, taken), news = index(newEnt, pairs);
    Object.keys(news).forEach(function (t) {
      if (news[t] && olds[t]) pairs[news[t]] = olds[t];
    });
    return pairs;
  }

  function union(rs) {
    var l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
    rs.forEach(function (x) {
      if (!x.width && !x.height) return;
      l = Math.min(l, x.left); t = Math.min(t, x.top); r = Math.max(r, x.right); b = Math.max(b, x.bottom);
    });
    return l === Infinity ? null : { left: l, top: t, width: r - l, height: b - t, right: r, bottom: b };
  }
  // A draw.io cell's box is its own shape: the group's own rectangle would take in the
  // cells nested in it, and a label's foreignObject is as large as the whole picture.
  function rectOf(g) {
    if (!g.hasAttribute('data-cell-id')) return g.getBoundingClientRect();
    var r = union(own(g, 'rect, path, ellipse, polygon, polyline, image').map(function (el) {
      return el.getBoundingClientRect();
    }));
    if (!r) {
      r = union(own(g, 'foreignObject').map(function (fo) {
        var d = fo.querySelector('div div') || fo.firstElementChild;
        return d ? d.getBoundingClientRect() : { width: 0, height: 0 };
      }).concat(own(g, 'text').map(function (el) { return el.getBoundingClientRect(); })));
    }
    return r || g.getBoundingClientRect();
  }
  function rects(map) {
    var out = {};
    Object.keys(map).forEach(function (k) { out[k] = rectOf(map[k]); });
    return out;
  }
  function centre(names, r) {
    var x = 0, y = 0;
    names.forEach(function (n) { x += r[n].left + r[n].width / 2; y += r[n].top + r[n].height / 2; });
    return { x: x / names.length, y: y / names.length };
  }
  // The diff's own boxes: the first ripple, or anything painted as added or removed.
  function isFocus(g) {
    var shape = g.querySelector(':scope > rect, :scope > path, :scope > polygon');
    var fill = shape ? (shape.getAttribute('fill') || '') : '';
    return /dgm-ripple-1|dgm-diff-(add|del)/.test(fill);
  }
  function scroller(el) {
    for (var p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      var oy = getComputedStyle(p).overflowY;
      if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay') && p.scrollHeight > p.clientHeight) return p;
    }
    return document.scrollingElement || document.documentElement;
  }
  // Screen pixels to the SVG's user units: the picture is scaled down by `max-width:100%`.
  function unit(svg) {
    var vb = svg.viewBox && svg.viewBox.baseVal;
    var w = svg.getBoundingClientRect().width;
    return vb && vb.width && w ? vb.width / w : 1;
  }

  function settle(diagram) {
    var done = diagram && diagram.__dgmMorphEnd;
    if (done) done();
  }

  // The animation itself, from a measured `before` to the picture now on screen in `to`.
  // o: { diagram, to, oldSvg, oldSvgR, oldEnt, oldR, oldEdges, newSvg, newEnt, newR, pairs }
  function play(o) {
    var diagram = o.diagram, to = o.to, newSvg = o.newSvg, newEnt = o.newEnt, newR = o.newR;
    var pairs = o.pairs, drawio = isDrawio(newSvg);
    var shared = Object.keys(newEnt).filter(function (n) { return n in pairs; });
    var arrived = Object.keys(newEnt).filter(function (n) { return !(n in pairs); });
    var kept = {};
    shared.forEach(function (n) { kept[pairs[n]] = true; });
    var left = Object.keys(o.oldEnt).filter(function (n) { return !kept[n]; });

    var still = !!(motion && motion.matches);
    var touched = [], ghost = null, timers = [], shapes = [];
    function end() {
      timers.forEach(clearTimeout);
      touched.forEach(function (el) {
        el.style.transition = el.style.transform = el.style.opacity = '';
        el.style.transformOrigin = el.style.transformBox = '';
        el.classList.remove('dgm-m-new', 'dgm-m-glow', 'dgm-m-in', 'dgm-m-fade');
      });
      shapes.forEach(function (el) { el.classList.remove('dgm-m-shape'); });
      if (ghost && ghost.parentNode) ghost.parentNode.removeChild(ghost);
      to.classList.remove('dgm-morphing');
      if (diagram.__dgmMorphEnd === end) diagram.__dgmMorphEnd = null;
    }
    diagram.__dgmMorphEnd = end;

    arrived.forEach(function (n) {
      var g = newEnt[n];
      touched.push(g);
      g.classList.add('dgm-m-glow');
      // draw.io's shape sits a few groups down, under a link and a crisp-edge offset.
      if (drawio) {
        var s = own(g, 'rect, path, ellipse, polygon')[0];
        if (s) { s.classList.add('dgm-m-shape'); shapes.push(s); }
      }
    });
    // New / Old of one PlantUML diagram shows the same boxes twice, so nothing arrives:
    // the change is a box whose content differs (a column gained), or a line drawn between
    // two boxes that were both already there (an association gained). Those glow too.
    // A line that came with a newcomer box is that box's news, already glowing.
    if (!drawio && o.oldSvg) {
      shared.forEach(function (n) {
        var g = newEnt[n];
        if (text(g) === text(o.oldEnt[pairs[n]])) return;
        touched.push(g);
        g.classList.add('dgm-m-glow');
      });
      var had = links(o.oldSvg), now = links(newSvg);
      Object.keys(now).forEach(function (k) {
        var l = now[k];
        if (k in had || !(l.ends[0] in pairs) || !(l.ends[1] in pairs)) return;
        touched.push(l.g);
        l.g.classList.add('dgm-m-glow');
      });
    }
    timers.push(setTimeout(end, (still ? 0 : MOVE) + GLOW));
    if (still) return;

    var k = unit(newSvg), svgR = newSvg.getBoundingClientRect(), shift = {};
    shared.forEach(function (n) {
      var b = o.oldR[pairs[n]], c = newR[n];
      shift[n] = [(b.left - c.left) * k, (b.top - c.top) * k];
    });
    // A draw.io box nested in another one rides along with it: it is moved only by the
    // part of its own slide that its container does not already give it.
    function carrier(g) {
      for (var p = g.parentNode && g.parentNode.closest ? g.parentNode.closest(CELL) : null; p;
           p = p.parentNode && p.parentNode.closest ? p.parentNode.closest(CELL) : null) {
        var id = p.getAttribute('data-cell-id');
        if (newEnt[id] === p && shift[id]) return shift[id];
      }
      return null;
    }
    shared.forEach(function (n) {
      var g = newEnt[n], tx = shift[n][0], ty = shift[n][1];
      var up = drawio ? carrier(g) : null;
      if (up) { tx -= up[0]; ty -= up[1]; }
      if (Math.abs(tx) < 0.5 && Math.abs(ty) < 0.5) return;
      touched.push(g);
      g.style.transition = 'none';
      g.style.transform = 'translate(' + tx + 'px,' + ty + 'px)';
    });
    arrived.forEach(function (n) {
      var g = newEnt[n];
      // Grow from the box's own centre: a draw.io label's foreignObject spans the whole
      // picture, so `fill-box` would grow it from the middle of the diagram.
      if (drawio) {
        var c = newR[n];
        g.style.transformBox = 'view-box';
        g.style.transformOrigin = ((c.left + c.width / 2 - svgR.left) * k) + 'px '
          + ((c.top + c.height / 2 - svgR.top) * k) + 'px';
      }
      g.classList.add('dgm-m-new');
    });
    waiting(newSvg).forEach(function (el) {
      // A draw.io line that is exactly where it was (Diff <-> New of one drawing, or a
      // line between two boxes that stayed) stays put: a blink on it would read as a change.
      var was = drawio && o.oldEdges && o.oldEdges[el.getAttribute('data-cell-id')];
      if (was) {
        var r = rectOf(el);
        if (Math.abs(r.left - was.left) < 0.5 && Math.abs(r.top - was.top) < 0.5
            && Math.abs(r.width - was.width) < 0.5 && Math.abs(r.height - was.height) < 0.5) return;
      }
      touched.push(el);
      el.classList.add('dgm-m-fade');
    });

    // Nothing slid, arrived, left or re-routed (Diff <-> New of one drawing): no morph.
    if (!left.length && !touched.length) { end(); return; }
    to.classList.add('dgm-morphing');

    // The ones that left: a copy of the old picture, pinned where it was, showing only them.
    if (left.length && o.oldSvgR) {
      var gone = {};
      left.forEach(function (n) { gone[n] = true; });
      ghost = o.oldSvg.cloneNode(true);
      ghost.removeAttribute('id');
      ghost.querySelectorAll('[id]').forEach(function (el) {
        if (el.tagName.toLowerCase() !== 'filter' && el.tagName.toLowerCase() !== 'lineargradient') el.removeAttribute('id');
      });
      if (drawio) {
        ghost.querySelectorAll(CELL).forEach(function (el) {
          var id = el.getAttribute('data-cell-id');
          el.style.visibility = gone[id] && cellKind(el) === 'vertex' ? 'visible' : 'hidden';
        });
      } else {
        ghost.querySelectorAll('g.entity[data-qualified-name], g.link, g.title, g.footer, g.caption, g.legend, g.cluster').forEach(function (el) {
          var n = el.getAttribute('data-qualified-name');
          if (!n || !gone[n] || !el.classList.contains('entity')) el.style.visibility = 'hidden';
        });
      }
      ghost.classList.add('dgm-m-ghost');
      var boxR = to.getBoundingClientRect();
      ghost.style.left = (o.oldSvgR.left - boxR.left - to.clientLeft + to.scrollLeft) + 'px';
      ghost.style.top = (o.oldSvgR.top - boxR.top - to.clientTop + to.scrollTop) + 'px';
      ghost.style.width = o.oldSvgR.width + 'px';
      ghost.style.height = o.oldSvgR.height + 'px';
      ghost.style.margin = '0';
      ghost.style.background = 'transparent';
      ghost.style.maxWidth = 'none';
      to.appendChild(ghost);
    }

    void to.offsetWidth;                                  // commit the starting frame
    requestAnimationFrame(function () {
      shared.forEach(function (n) {
        var g = newEnt[n];
        if (!g.style.transform) return;
        g.style.transition = 'transform ' + MOVE + 'ms cubic-bezier(.2,.7,.2,1)';
        g.style.transform = '';
      });
      arrived.forEach(function (n) { newEnt[n].classList.add('dgm-m-in'); });
      if (ghost) ghost.classList.add('dgm-m-out');
      timers.push(setTimeout(function () {
        newSvg.querySelectorAll('.dgm-m-fade').forEach(function (el) { el.classList.add('dgm-m-in'); });
      }, MOVE * 0.8));
    });
  }

  function morph(diagram, bar, button) {
    var level = button.getAttribute('data-level');
    var from = diagram.querySelector('.svgbox[data-level]:not([hidden])');
    var to = null;
    diagram.querySelectorAll('.svgbox[data-level]').forEach(function (b) {
      if (b.getAttribute('data-level') === level) to = b;
    });
    settle(diagram);
    if (!from || !to || from === to) return;

    var oldSvg = svgOf(from), newSvg = svgOf(to);
    var oldEnt = entities(oldSvg), oldR = rects(oldEnt), oldSvgR = oldSvg && oldSvg.getBoundingClientRect();

    // The flip itself, identical to the chooser's.
    bar.querySelectorAll('button[data-level]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b === button));
    });
    diagram.querySelectorAll('.svgbox[data-level]').forEach(function (b) {
      b.hidden = b !== to;
    });
    if (!oldSvg || !newSvg) return;

    var newEnt = entities(newSvg), newR = rects(newEnt);
    var pairs = match(oldEnt, newEnt, isDrawio(newSvg));
    var shared = Object.keys(newEnt).filter(function (n) { return n in pairs; });

    // Anchor: keep the change where it was on screen. Only the page scrolls, so the
    // final picture is exactly the un-animated one; whatever the scroll cannot absorb
    // (the top of the page, or the chooser itself about to leave the screen) is left to
    // the slide below.
    var anchors = shared.filter(function (n) { return isFocus(newEnt[n]); });
    if (!anchors.length) anchors = shared;
    if (anchors.length) {
      var was = {};
      anchors.forEach(function (n) { was[n] = oldR[pairs[n]]; });
      var a = centre(anchors, was), b = centre(anchors, newR);
      var sc = scroller(to), dy = b.y - a.y;
      var top = sc === document.scrollingElement || sc === document.documentElement
        ? 0 : sc.getBoundingClientRect().top;
      // A chooser that does not pin (an older stylesheet) must not be scrolled away.
      if (dy > 0 && getComputedStyle(bar).position !== 'sticky') {
        dy = Math.min(dy, Math.max(0, bar.getBoundingClientRect().top - top - 8));
      }
      var before = sc.scrollTop;
      sc.scrollTop = before + dy;
      var dx = b.x - a.x;
      if (to.scrollWidth > to.clientWidth) to.scrollLeft += dx;
      if (sc.scrollTop !== before || dx) newR = rects(newEnt);
    }

    play({ diagram: diagram, to: to, oldSvg: oldSvg, oldSvgR: oldSvgR, oldEnt: oldEnt, oldR: oldR,
           newSvg: newSvg, newEnt: newEnt, newR: newR, pairs: pairs });
  }

  document.addEventListener('click', function (ev) {
    var button = ev.target && ev.target.closest && ev.target.closest('.diagram .focus button[data-level]');
    if (!button) return;
    var bar = button.closest('.focus'), diagram = button.closest('.diagram');
    try { morph(diagram, bar, button); } catch (e) { settle(diagram); }
  }, true);

  // Diff / New / Old, on a hand-drawn (draw.io) card and on a PlantUML one (the Data tab's
  // domain model and ERD, the Structure tab's views). The switch has already flipped the
  // panes when this runs, so the pane it left is shown again for one synchronous read of
  // where its boxes were — layout only, nothing is painted in between. No anchoring
  // scroll here, unlike the radius: the Diff / New / Old bar does not pin, and the next
  // click on it must land where the last one did.
  function paneOf(views, state) {
    return views.querySelector(':scope > .dgmpane[data-view="' + state + '"]');
  }
  function shownSvg(pane) { return svgOf(pane && pane.querySelector('.svgbox:not([hidden])')); }
  function swap(views, was) {
    var now = views.getAttribute('data-state');
    if (!was || was === now) return;
    var from = paneOf(views, was), to = paneOf(views, now);
    var diagram = views.closest('.diagram') || views;
    settle(diagram);
    if (!from || !to || from === to) return;
    var oldSvg = shownSvg(from), newSvg = shownSvg(to);
    var drawio = isDrawio(oldSvg) && isDrawio(newSvg);
    if (!drawio && !(hasBoxes(oldSvg) && hasBoxes(newSvg))) return;
    var fromHidden = from.hidden, toHidden = to.hidden;
    to.hidden = true; from.hidden = false;
    var oldEnt, oldR, oldSvgR, oldEdges = {};
    try {
      oldSvgR = oldSvg.getBoundingClientRect();
      oldEnt = entities(oldSvg); oldR = rects(oldEnt);
      if (drawio) waiting(oldSvg).forEach(function (g) { oldEdges[g.getAttribute('data-cell-id')] = rectOf(g); });
    } finally {
      from.hidden = fromHidden; to.hidden = toHidden;
    }
    if (!oldSvgR.width) return;                          // a card on a tab nobody is looking at
    var newEnt = entities(newSvg);
    play({ diagram: diagram, to: newSvg.parentNode, oldSvg: oldSvg, oldSvgR: oldSvgR, oldEnt: oldEnt,
           oldR: oldR, oldEdges: oldEdges, newSvg: newSvg, newEnt: newEnt, newR: rects(newEnt),
           pairs: match(oldEnt, newEnt, drawio) });
  }
  if (window.MutationObserver) {
    new MutationObserver(function (records) {
      records.forEach(function (r) {
        var views = r.target;
        if (!views.classList || !views.classList.contains('dgmviews')) return;
        try { swap(views, r.oldValue); } catch (e) { settle(views.closest('.diagram') || views); }
      });
    }).observe(document.documentElement, { subtree: true, attributes: true,
                                           attributeFilter: ['data-state'], attributeOldValue: true });
  }
})();
