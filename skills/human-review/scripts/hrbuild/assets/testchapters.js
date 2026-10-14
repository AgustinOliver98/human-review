// The Tests tab's card, read by kind of test rather than by requirement sentence.
//
// The card used to list each test under the ticket sentence it was paired with. That
// pairing is a reading (a script's or a model's) and it moved between runs, so the card's
// shape moved with it (Victor, 7 Oct 2026: "flaky, unstable, opinionated"). What a test IS
// does not move: E2E, API or unit. So the rows go into three collapsible chapters, headed
// by the same badge each row already wears; the pairing still paints the ticket on the
// left and still lights the rows a sentence click picks, it just no longer files them.
//
// The chapters replace the E2E/API/UNIT filter checkboxes: a chapter that is closed is the
// filter. In their place, one checkbox: "Show all tests". Off, the card lists what it always
// did by default. On, it also lists what used to sit behind the fold buttons, and every
// other test the coverage run executed (`#rm-all-tests`, written by tests.py
// `all_tests_inventory`): name, badge and file link only - no preview to open, so the
// arrow's slot stays blank and the columns stay put. Those rows are built on the first
// check, not at load: a big repo runs thousands of tests and nobody asked for them yet.
//
// The renderer (reqmap.js) is left to draw the rows; this moves them, after the fact, the
// same way trace.js and seqlink.js decorate them from the outside.
(function () {
  var map = document.querySelector('.reqmap');
  if (!map) return;
  var list = map.querySelector('.rm-code .rm-list');
  if (!list || list.querySelector('.rm-ch')) return;
  var D = {};
  try { D = JSON.parse(map.querySelector('.rm-data').textContent); } catch (e) { D = {}; }
  var TESTS = D.tests || {}, LABEL = D.cats || {e2e: 'E2E', api: 'API', unit: 'Unit'};
  // The subtitles, as few words as say what the badge alone does not.
  var CH = [['e2e', 'end-to-end, from the browser'],
            ['api', 'calling the API directly'],
            ['unit', 'one component, isolated']];
  // Which chapters start open: none (Victor, 7 Oct 2026). Each heading carries its own
  // +added / -deleted / edited counts, so the closed card reads as a summary by kind.
  var OPEN = {};

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }
  // reqmap.js's own unpacking of an identifier into words, so an added row reads like
  // the rows around it.
  function human(name) {
    name = String(name || '');
    if (/\s/.test(name)) return name;
    var w = name.replace(/[_\-]+/g, ' ')
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
      .split(/\s+/).filter(Boolean)
      .map(function (x) { return /^[A-Z0-9]{2,}$/.test(x) ? x : x.toLowerCase(); });
    return w.length ? w[0].charAt(0).toUpperCase() + w[0].slice(1)
      + (w.length > 1 ? ' ' + w.slice(1).join(' ') : '') : name;
  }
  // `OwnerListTest.java` -> `.java`, `add-visit.component.spec.ts` -> `.spec.ts`: the
  // same face the card's own file links wear.
  function ext(file) {
    var m = /((?:\.(?:spec|test|e2e-spec|e2e|cy|it))?\.[A-Za-z0-9]+)$/i.exec(file || '');
    return m ? m[1] : (file || '');
  }
  function catOf(row) {
    var b = row.querySelector('.rm-thead .rm-cat');
    return (b && b.dataset.cat) || 'unit';
  }

  // ---- the chapters --------------------------------------------------------------------
  var chapters = {};
  CH.forEach(function (c) {
    var sec = document.createElement('section');
    sec.className = 'rm-ch';
    sec.dataset.cat = c[0];
    sec.dataset.open = OPEN[c[0]] ? 'yes' : 'no';
    // The caret first, in the column the rows keep for their wire button, so the badge
    // stands over the rows' badges; a blank arrow's width after it, so the subtitle starts
    // where the test names do. The counts close the row, in the column the card title's
    // own `+42 -12 ✍5` stands in.
    sec.innerHTML = '<div class="rm-chh" role="button" tabindex="0" aria-expanded="'
      + (OPEN[c[0]] ? 'true' : 'false') + '">'
      + '<span class="rm-chev rm-chcaret" aria-hidden="true">&#9654;</span>'
      + '<span class="rm-cat" data-cat="' + c[0] + '">' + esc(LABEL[c[0]] || c[0]) + '</span>'
      + '<span class="rm-chev rm-chpad" aria-hidden="true">&#9654;</span>'
      + '<span class="rm-chsub">' + esc(c[1]) + ' <span class="rm-chn"></span></span>'
      + '<span class="rm-chled"></span></div>'
      + '<div class="rm-chb"><div class="rm-cho"></div></div>';
    chapters[c[0]] = sec;
  });

  // Stable hooks on every row, for whatever else decorates them from outside (the
  // fixture dot, the replay, the sequence link): the kind, the file, the test's own name.
  function hook(row) {
    var id = (row.dataset.id || '').replace(/@base$/, '');
    if (!row.dataset.cat) row.dataset.cat = catOf(row);
    if (id && !row.dataset.file) row.dataset.file = id.replace(/:\d+$/, '');
    var t = TESTS[row.dataset.id];
    if (t && !row.dataset.testName) row.dataset.testName = t.title || '';
  }
  Array.prototype.slice.call(list.children).forEach(function (el) {
    if (el.classList.contains('rm-t')) {
      hook(el);
      var sec = chapters[el.dataset.cat] || chapters.unit;
      var body = sec.querySelector('.rm-chb');
      body.insertBefore(el, body.querySelector('.rm-cho'));
    } else if (el.classList.contains('rm-tgroup')) {
      el.parentNode.removeChild(el);        // the sentence headings: no longer the grouping
    }
    // `.rm-fold` buttons stay in the list, hidden by the stylesheet: "All tests" is what
    // opens what they used to.
  });
  CH.forEach(function (c) { list.appendChild(chapters[c[0]]); });

  // ---- the "All tests" checkbox, on the card's own title row ---------------------------
  // Right-aligned on the "Tests covering the change set" strip, just before the changed-
  // tests counts (Victor, 7 Oct 2026): it changes what that card lists, so it sits on the
  // card. The filters it replaces stood over the card; their chips go.
  var inv = document.getElementById('rm-all-tests'), INV = null;
  var bar = map.querySelector('.rm-cats');
  if (bar) Array.prototype.forEach.call(bar.querySelectorAll('.rm-catf, .rm-allf'), function (x) {
    x.parentNode.removeChild(x);
  });
  var lab = document.createElement('label');
  lab.className = 'rm-allf';
  lab.innerHTML = '<input type="checkbox"> Show all tests';
  var head = map.querySelector('.rm-code > .rm-tkhead');
  if (head) head.insertBefore(lab, head.querySelector('.tledger'));
  var box = head ? lab.querySelector('input') : null;
  Array.prototype.forEach.call(list.querySelectorAll('.rm-t[data-catoff]'), function (r) {
    delete r.dataset.catoff;
  });
  var total = 0;
  if (inv) { try { total = (JSON.parse(inv.textContent).tests || []).length; } catch (e) {} }
  if (box) {
    var label = box.closest('label');
    label.setAttribute('data-tip', total
      ? 'Also list the ' + total + ' other tests that ran: name and file only'
      : 'Also list the tests folded away: pass-through, unmeasured, deleted');
  }

  function otherRow(t) {
    var file = t.file || '', cat = CH.some(function (c) { return c[0] === t.cat; }) ? t.cat : 'unit';
    var link = t.href
      ? '<a class="rm-tw srcref" href="' + esc(t.href) + '" data-tip="' + esc(file + ':' + t.line)
        + ' — Open in VS Code" target="_blank" rel="noopener" data-ext-only="">'
        + esc(ext(file.split('/').pop())) + '</a>'
      : '<span class="rm-tw"></span>';
    return '<div class="rm-t rm-other" data-shut="yes" data-open="no" data-cat="' + cat
      + '" data-file="' + esc(file) + '" data-test-name="' + esc(t.title) + '">'
      + '<div class="rm-thead">'
      + '<button class="rm-link" type="button" disabled tabindex="-1" aria-hidden="true"></button>'
      + '<span class="rm-cat" data-cat="' + cat + '">' + esc(LABEL[cat] || cat) + '</span>'
      + '<span class="rm-chev" aria-hidden="true">&#9654;</span>'
      + '<span class="rm-tt">' + esc(human(t.title)) + '</span>'
      + link
      + '<span class="rm-run" aria-hidden="true"></span>'
      + '<span class="rm-st rm-st-none" aria-hidden="true"></span></div></div>';
  }
  function buildOthers() {
    if (INV || !inv) return;
    try { INV = JSON.parse(inv.textContent).tests || []; } catch (e) { INV = []; }
    var html = {};
    INV.forEach(function (t) {
      var c = chapters[t.cat] ? t.cat : 'unit';
      html[c] = (html[c] || '') + otherRow(t);
    });
    Object.keys(html).forEach(function (c) {
      chapters[c].querySelector('.rm-cho').innerHTML = html[c];
    });
  }

  function folded(row) {
    return row.dataset.fold === 'yes' || row.dataset.own === 'yes' || row.dataset.del === 'yes';
  }
  function count() {
    var all = list.dataset.all === 'yes';
    CH.forEach(function (c) {
      var sec = chapters[c[0]], n = 0;
      Array.prototype.forEach.call(sec.querySelectorAll('.rm-t'), function (r) {
        if (r.classList.contains('rm-other') ? all : (all || !folded(r))) n++;
      });
      sec.querySelector('.rm-chn').textContent = '\u00B7 ' + n;
      sec.hidden = !n;
      // What the branch did to this kind's tests: the card title's three counts, for one
      // chapter, off the stamps its rows already wear. Every row is counted, folded or not.
      var st = {new: 0, deleted: 0, edited: 0};
      Array.prototype.forEach.call(sec.querySelectorAll('.rm-t .rm-st[data-st]'), function (s) {
        if (s.dataset.st in st) st[s.dataset.st]++;
      });
      // Three slots, always, an empty one kept (Victor, 14 Oct 2026: "align in columns"):
      // a `+`, a `−` and a ✍️ column, so the chapters' counts and the card title's stand
      // one under the other instead of sliding right whenever a sign is missing.
      sec.querySelector('.rm-chled').innerHTML =
        (st.new ? '<span class="added" data-tip="' + st.new + ' new ' + c[0].toUpperCase()
          + ' test' + (st.new === 1 ? '' : 's') + '">+' + st.new + '</span>' : '<span></span>')
        + (st.deleted ? '<span class="removed" data-tip="' + st.deleted + ' ' + c[0].toUpperCase()
          + ' test' + (st.deleted === 1 ? '' : 's') + ' gone">\u2212' + st.deleted + '</span>' : '<span></span>')
        + (st.edited ? '<span class="changed" data-tip="' + st.edited + ' ' + c[0].toUpperCase()
          + ' test' + (st.edited === 1 ? '' : 's') + ' edited">\u270D\uFE0F' + st.edited + '</span>' : '<span></span>');
    });
  }
  function setAll(on) {
    if (on) buildOthers();
    list.dataset.all = on ? 'yes' : 'no';
    // The card title's hover says what the list is, so it follows the checkbox (tests.py
    // COVCARD_TIP / COVCARD_TIP_ALL).
    var tipEl = map.querySelector('.rm-code > .rm-tkhead .cov-head[data-tip]')
             || map.querySelector('.rm-code > .rm-tkhead .rm-who[data-tip]');
    if (tipEl) tipEl.setAttribute('data-tip', on
      ? 'All tests, as captured by a coverage probe.'
      : 'Tests that ran a changed line, as captured by a coverage probe.');
    ['unfold', 'unown', 'undel'].forEach(function (k) { list.dataset[k] = on ? 'yes' : 'no'; });
    count();
    window.dispatchEvent(new Event('resize'));       // the wires follow the rows
  }
  if (box) box.addEventListener('change', function () { setAll(box.checked); });
  setAll(!!(box && box.checked));

  // ---- open / close ---------------------------------------------------------------------
  function openCh(sec, on) {
    sec.dataset.open = on ? 'yes' : 'no';
    sec.querySelector('.rm-chh').setAttribute('aria-expanded', on ? 'true' : 'false');
  }
  list.addEventListener('click', function (e) {
    var h = e.target.closest('.rm-chh');
    if (!h) return;
    var sec = h.parentNode;
    openCh(sec, sec.dataset.open !== 'yes');
    window.dispatchEvent(new Event('resize'));
  });
  list.addEventListener('keydown', function (e) {
    var h = e.target.closest && e.target.closest('.rm-chh');
    if (!h || (e.key !== 'Enter' && e.key !== ' ')) return;
    e.preventDefault();
    openCh(h.parentNode, h.parentNode.dataset.open !== 'yes');
    window.dispatchEvent(new Event('resize'));
  });

  // A sentence picked on the left lights its tests on the right (reqmap.js `open`). A lit
  // row in a closed chapter would be lit where nobody can see it, so its chapter opens and
  // the first lit row is brought to the top of the card. Runs after the renderer's own
  // handler: it is registered later on the same element.
  function reveal() {
    if (list.dataset.sel !== 'yes') return;
    var hits = Array.prototype.filter.call(list.querySelectorAll('.rm-t[data-hit=yes]'),
      function (r) { return !folded(r) || list.dataset.all === 'yes'; });
    if (!hits.length) return;
    hits.forEach(function (r) { var s = r.closest('.rm-ch'); if (s) openCh(s, true); });
    var top = hits[0].getBoundingClientRect().top - list.getBoundingClientRect().top;
    if (top < 0 || top > list.clientHeight - 30) list.scrollTop += top - 4;
    window.dispatchEvent(new Event('resize'));
  }
  map.addEventListener('click', function (e) { if (e.target.closest('.rm-f')) reveal(); });

  // ---- the shield: which code this test really runs ---------------------------------------
  // The row's 🛡 used to say "Runs changed code: a.ts:13-15... +6 files", one line, gone
  // the moment the pointer left it. Its question is "what part of the code is this test
  // really covering?", and the answer is a list of files a reader wants to open. So it is
  // a popover that stays while the pointer travels into it: the changed files first, with
  // how many changed lines the test ran in each, then the rest; each name is the page's
  // ordinary `vscode://` link (`#rm-test-cover`, written by tests.py `test_cover_files`).
  var COVER = {};
  try { COVER = JSON.parse(document.getElementById('rm-test-cover').textContent) || {}; }
  catch (e) { COVER = {}; }
  var pop = null, popFor = null, showT = 0, hideT = 0;
  function coverHtml(c) {
    var ch = c.files.filter(function (f) { return f[2] > 0; }),
        rest = c.files.filter(function (f) { return !f[2]; });
    function li(f) {
      var name = f[0].split('/').pop();
      return '<li><a href="' + esc(f[3]) + '" data-path="' + esc(f[0]) + '">' + esc(name) + '</a>'
        + (f[2] ? ' <span class="rm-cpn">' + f[2] + ' changed line' + (f[2] === 1 ? '' : 's')
          + '</span>' : '') + '</li>';
    }
    return (ch.length ? '<p class="rm-cph">Changed code it runs</p><ul class="tiplist">'
        + ch.map(li).join('') + '</ul>' : '')
      + (rest.length ? '<p class="rm-cph">Also runs</p><ul class="tiplist">'
        + rest.map(li).join('') + '</ul>' : '')
      + (c.more ? '<p class="rm-cpm">+' + c.more + ' more file' + (c.more === 1 ? '' : 's')
        + '</p>' : '');
  }
  function placePop(el) {
    var r = el.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8));
    var top = r.bottom + 4;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 4);
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
  }
  function showPop(el) {
    var row = el.closest('.rm-t'), c = row && COVER[(row.dataset.id || '').replace(/@base$/, '')];
    if (!c) return;
    if (!pop) {
      pop = document.createElement('div');
      pop.className = 'rm-covpop';
      pop.setAttribute('role', 'tooltip');
      pop.addEventListener('pointerenter', function () { clearTimeout(hideT); });
      pop.addEventListener('pointerleave', function () { hideSoon(); });
      document.body.appendChild(pop);
    }
    pop.innerHTML = coverHtml(c);
    popFor = el;
    pop.classList.add('on');
    placePop(el);
  }
  function hidePop() { if (pop) pop.classList.remove('on'); popFor = null; }
  function hideSoon() { clearTimeout(showT); clearTimeout(hideT); hideT = setTimeout(hidePop, 250); }
  function arm(row) {
    var run = row.querySelector('.rm-run');
    if (!run || !COVER[(row.dataset.id || '').replace(/@base$/, '')]) return;
    // The page's one-line tip would open on top of the popover: the popover says more.
    run.removeAttribute('data-tip');
    run.dataset.cover = 'yes';
  }
  Array.prototype.forEach.call(list.querySelectorAll('.rm-t[data-id]'), arm);
  list.addEventListener('pointerover', function (e) {
    var run = e.target.closest && e.target.closest('.rm-run[data-cover]');
    if (!run) return;
    clearTimeout(hideT);
    if (popFor === run) return;
    clearTimeout(showT);
    showT = setTimeout(function () { showPop(run); }, 150);
  });
  list.addEventListener('pointerout', function (e) {
    var run = e.target.closest && e.target.closest('.rm-run[data-cover]');
    if (run && !run.contains(e.relatedTarget)) hideSoon();
  });
  list.addEventListener('scroll', hidePop, {passive: true});
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hidePop(); });
  map.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.closest && e.target.closest('.rm-f')) reveal();
  });
})();
