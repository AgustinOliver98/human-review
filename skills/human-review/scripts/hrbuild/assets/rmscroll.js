// The Tests tab's two panes - the ticket's prose (`.rm-issue`) and the card's list of tests
// (`.rm-list`) - scroll on their own, and a classic scrollbar took 15px out of each and
// pushed everything in it left (Victor, 19 Oct 2026: "this screen is very crowded, I want
// to make the best of the horizontal space"). Chromium has no overlay scrollbars to ask
// for any more (`overflow:overlay` is gone), so the native bar is hidden (tests.py
// REQMAP_CSS, `.rm-ovs`) and this draws one over the content instead: a thin thumb on the
// pane's right edge, out of sight until the pane is pointed at (faint) or scrolled (half
// strength, for a moment after the wheel stops), and draggable like the real one. The
// wheel, the keys and a trackpad scroll the pane natively, as before.
(function () {
  var panes = document.querySelectorAll('.reqmap .rm-issue, .reqmap .rm-list');
  if (!panes.length) return;
  Array.prototype.forEach.call(panes, function (pane) {
    var host = pane.parentNode;
    pane.classList.add('rm-ovs');
    var bar = document.createElement('div');
    bar.className = 'rm-ovbar';
    bar.setAttribute('aria-hidden', 'true');
    host.appendChild(bar);
    var idle = 0, drag = null;

    function place() {
      var ch = pane.clientHeight, sh = pane.scrollHeight;
      var scrolls = sh > ch + 1 && /auto|scroll/.test(getComputedStyle(pane).overflowY);
      bar.hidden = !scrolls;
      if (!scrolls) return;
      var h = Math.max(24, Math.round(ch * ch / sh));
      var y = pane.offsetTop + Math.round((ch - h) * pane.scrollTop / (sh - ch));
      bar.style.top = y + 'px';
      bar.style.height = h + 'px';
    }
    function flash() {
      place();
      bar.classList.add('on');
      clearTimeout(idle);
      idle = setTimeout(function () { if (!drag) bar.classList.remove('on'); }, 900);
    }
    pane.addEventListener('scroll', flash, {passive: true});
    host.addEventListener('pointerenter', function () { place(); bar.classList.add('near'); });
    host.addEventListener('pointerleave', function () { bar.classList.remove('near'); });
    bar.addEventListener('pointerdown', function (e) {
      e.preventDefault();
      drag = {y: e.clientY, top: pane.scrollTop};
      bar.setPointerCapture(e.pointerId);
      bar.classList.add('on');
    });
    bar.addEventListener('pointermove', function (e) {
      if (!drag) return;
      var ch = pane.clientHeight, sh = pane.scrollHeight, h = bar.offsetHeight;
      pane.scrollTop = drag.top + (e.clientY - drag.y) * (sh - ch) / Math.max(1, ch - h);
    });
    function drop() { drag = null; flash(); }
    bar.addEventListener('pointerup', drop);
    bar.addEventListener('pointercancel', drop);
    // The content grows and shrinks under it - a chapter opening, a test's source, the
    // tab being shown at all - and none of that is a scroll event.
    window.addEventListener('resize', place);
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(place);
      ro.observe(pane);
      Array.prototype.forEach.call(pane.children, function (c) { ro.observe(c); });
      if (window.MutationObserver) {
        new MutationObserver(function () {
          Array.prototype.forEach.call(pane.children, function (c) { ro.observe(c); });
          place();
        }).observe(pane, {childList: true});
      }
    }
    pane.addEventListener('transitionend', place);
    place();
  });
})();
