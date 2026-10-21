// One coloured dot per DB fixture on each row of the Tests tab whose test starts on a dataset
// (`hrbuild/shared/fixtures.py`): the fixture an E2E test declares (`@fixture:<name>`,
// `test.use({dbFixture: …})`), the `@Sql` / `@DefaultFixture` of a Spring test, or the seed its
// Flyway config loads. The colours are the project's, from a `fixture-colors.json` beside the
// fixtures' SQL; the seed is always grey. (The Demo tab's "DB Fixture" card wears the same dots,
// drawn by the build itself.)
//
// No dot means the test starts on an EMPTY database — it declares no fixture (Victor, 21 Oct
// 2026). So the dot is never a guess: the hollow "Default, but leans on none of its rows" ring
// and the dashed "a hook truncates" ring went with the assumption that every test ran on the
// seed. A unit row gets nothing either: the registry only names tests that start on data.
//
// The rows are drawn by the Tests tab's own script and regrouped since by testchapters.js,
// so the dots are put on from the outside, idempotently, and put back by a
// MutationObserver whenever either redraws.
(function () {
  var el = document.getElementById('hr-fixtures');
  if (!el) return;
  var reg; try { reg = JSON.parse(el.textContent); } catch (e) { return; }
  var colors = reg.colors || {}, tests = reg.tests || {};
  var palette = reg.palette && reg.palette.length ? reg.palette : ['#3b82f6'];

  // A fixture the build never saw (added to the project after this page was made) still
  // gets a colour: the one its name hashes to, as `fixture_hue` does in fixtures.py.
  function colourOf(name) {
    if (!name || name === 'seed') return reg.seed || '#8b929c';
    if (colors[name]) return colors[name];
    var h = 0;
    for (var k = 0; k < name.length; k++) h = (Math.imul(h, 31) + name.charCodeAt(k)) >>> 0;
    return palette[h % palette.length];
  }
  function dot(colour, tip) {
    var d = document.createElement('span');
    d.className = 'fx-dot';
    d.setAttribute('role', 'img');
    d.setAttribute('aria-label', tip);
    d.setAttribute('data-tip', tip);
    d.style.setProperty('--fx', colour);
    return d;
  }
  function said(name) {
    // The Demo card's own words, so the row and the card read as one thing:
    // "DB Fixture: Default" / "DB Fixture: green".
    return 'DB Fixture: ' + (name === 'seed' ? 'Default' : name)
      + ' \u00b7 click to view the data';
  }

  // A row's dot is a way into that fixture's data, the same tables the Demo tab's DB
  // Fixture card opens under that fixture's header: `window.hrOpenDataset(name)` when the
  // dataset view is on the page, with the name its header carries ("" for Default, as its
  // data-fixture has it); without it, the Demo tab, scrolled to the DB Fixture card, with
  // this fixture's Seed in focus.
  function open(name) {
    var key = name === 'seed' ? '' : name;
    if (typeof window.hrOpenDataset === 'function') { window.hrOpenDataset(key); return; }
    var tab = document.getElementById('tabbtn-behaviour');
    if (tab) tab.click();
    setTimeout(function () {
      var group = document.querySelector('.appenv-fixtures') || document.querySelector('.appenv');
      if (!group) return;
      group.scrollIntoView({block: 'center', behavior: 'smooth'});
      var btn = Array.prototype.filter.call(group.querySelectorAll('.appenv-reset'),
        function (b) { return (b.dataset.fixture || '') === key && !b.hidden; })[0];
      if (btn) { try { btn.focus({preventScroll: true}); } catch (e) { btn.focus(); } }
    }, 60);
  }
  // Capture, so the press never reaches the row head under it, which would fold the row.
  function onRowDot(ev) {
    var d = ev.target.closest && ev.target.closest('.rm-t .fx-dot');
    if (!d) return;
    if (ev.type === 'keydown' && ev.key !== 'Enter' && ev.key !== ' ') return;
    ev.preventDefault(); ev.stopPropagation();
    open(d.dataset.fixture || 'seed');
  }
  document.addEventListener('click', onRowDot, true);
  document.addEventListener('keydown', onRowDot, true);

  function rows() {
    Array.prototype.forEach.call(document.querySelectorAll('.rm-t[data-id]'), function (row) {
      var id = row.getAttribute('data-id') || '';
      // On any row the registry names, whatever its badge: the registry only lists tests
      // that start on a dataset (an API row was E2E-only until 19 Oct 2026, so the API
      // chapter never showed what its Spring tests boot with).
      var name = tests[id];
      var have = row.querySelector('.fx-dot');
      if (have && have.dataset.fixture !== name) { have.remove(); have = null; }
      if (!name) {
        if (have) have.remove();
        return;
      }
      // After the icons (🎭 replay, ⇥ sequence), right before the file-extension link —
      // which trace.js and seqlink.js insert in front of too, so a dot that arrived first
      // is moved back behind them.
      var tw = row.querySelector('.rm-tw');
      var head = tw ? tw.parentNode : row.querySelector('.rm-thead');
      if (!head) return;
      if (!have) {
        have = dot(colourOf(name), said(name));
        have.setAttribute('role', 'button');
        have.setAttribute('tabindex', '0');
        have.dataset.fixture = name;
      }
      if (tw ? have.nextElementSibling !== tw || have.parentNode !== head
             : have.parentNode !== head) {
        head.insertBefore(have, tw || null);
      }
    });
  }

  var queued = false;
  function run() {
    queued = false;
    rows();
  }
  function later() {
    if (queued) return;
    queued = true;
    (window.requestAnimationFrame || setTimeout)(run);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
  // Whatever redraws a row — the Tests tab's script, the chapters regrouping —
  // the dots follow on the next frame. `run` changes nothing on a page already dotted,
  // so its own insertions settle after one pass.
  new MutationObserver(later).observe(document.body, {childList: true, subtree: true,
                                                      attributes: true,
                                                      attributeFilter: ['hidden']});
})();
