// The Sequence tab opens on its table of contents: every test pair folded shut, so the
// tab's first screen is one line per test instead of the top of whichever sequence happens
// to be first. A sequence is three or four screens of arrows; four of them stacked is a
// wall the reader has to scroll past to find out what is on the tab at all.
//
// Why here and not `<details>` without `open` in the markup, which is the obvious way: the
// click targets inside every diagram are transparent rects sized from `getBBox()`, and
// `getBBox()` on anything inside a `display:none` subtree returns zeros. A pair born shut
// would cost its sequence every handle on it, silently. So the pairs are born open, every
// script that measures them runs, and the folding happens after — the same bargain TABS_JS
// makes with the panels, for the same reason, and this runs before it for the same one.
//
// A reader arriving on a deep link is the exception: the pair the link names is what they
// asked for, and it stays open.
//
// Which pair is open is in the URL, both ways round. A reader who opens one and sends the
// address sends the picture they are looking at, not the tab it is on — the same handle
// the ⇥ on the Tests tab already jumps through. `replaceState`, not `location.hash`,
// because assigning the hash scrolls the page out from under the click that caused it.
(function () {
  var wanted = decodeURIComponent((location.hash || '').slice(1));
  // Not scoped to a panel id: the tab this block lands on is named by the content file.
  document.querySelectorAll('details.testpair[open]').forEach(function (pair) {
    if (pair.id && pair.id === wanted) return;
    pair.open = false;
  });

  function remember(id) {
    if (history.replaceState) history.replaceState(null, '', '#' + id);
    else location.hash = id;
  }

  // At load, and over a panel a rebuild swaps in (`hr:swapped`, panels.js), which keeps
  // the reader's folds itself and only needs its pairs to keep reporting them.
  function wire(root) {
  root.querySelectorAll('details.testpair[id]').forEach(function (pair) {
    // `toggle` fires asynchronously, so the folding above arrives here too — harmlessly:
    // a pair being shut only rewrites the hash when the hash is naming that very pair,
    // which at load is true of the one pair this loop leaves open.
    pair.addEventListener('toggle', function () {
      var hash = decodeURIComponent((location.hash || '').slice(1));
      if (pair.open) remember(pair.id);
      else if (hash === pair.id) {
        var panel = pair.closest('.panel');
        remember(panel && panel.id ? panel.id : '');
      }
    });
  });
  }
  wire(document);
  document.addEventListener('hr:swapped', function (ev) {
    if (ev.detail && ev.detail.querySelectorAll) wire(ev.detail);
  });

  // The row's file name is a link — to VS Code, at the scenario's line — and it sits inside
  // the pair's <summary>, so a click on it is also a click on the row: the reader would open
  // the file AND have the row fold open or shut under them.
  //
  // The fold is put back rather than the click stopped. `stopPropagation` is the usual
  // remedy and it is wrong here: the handler that opens a `vscode://` reference through the
  // served page's editor helper is a listener on `document`, so silencing the event on its
  // way there would trade one bug for a better-hidden one. This runs after the browser's own
  // activation behaviour and before the next paint, so a fold that never moved is left
  // alone and one that did is put back with nothing drawn in between.
  document.addEventListener('click', function (ev) {
    var link = ev.target.closest && ev.target.closest('details.testpair > summary a');
    if (!link) return;
    var fold = link.closest('details.testpair');
    var was = fold.open;
    requestAnimationFrame(function () { if (fold.open !== was) fold.open = was; });
  }, true);

  // The DB fixture dot before a test's file name opens that fixture's data, as the same dot does
  // on the Tests tab — where the Demo tab's dataset view is on the page to open it. It sits
  // in the summary, so the press is taken before the row folds under it. Without the view
  // the dot stays a mark, and its tip promises no click.
  if (typeof window.hrOpenDataset === 'function') {
    var dots = function (root) {
      root.querySelectorAll('details.testpair > summary .fx-dot').forEach(function (dot) {
        dot.setAttribute('role', 'button');
        dot.setAttribute('tabindex', '0');
        var tip = dot.getAttribute('data-tip') + (dot.classList.contains('fx-empty')
          ? ' · click to view the rest' : ' · click to view the data');
        dot.setAttribute('data-tip', tip);
        dot.setAttribute('aria-label', tip);
      });
    };
    dots(document);
    document.addEventListener('hr:swapped', function (ev) {
      if (ev.detail && ev.detail.querySelectorAll) dots(ev.detail);
    });
    var onDot = function (ev) {
      var dot = ev.target.closest && ev.target.closest('details.testpair > summary .fx-dot');
      if (!dot) return;
      if (ev.type === 'keydown' && ev.key !== 'Enter' && ev.key !== ' ') return;
      // preventDefault alone keeps the row from folding; the event still travels on, as
      // every click inside a pair must (see the file link below).
      ev.preventDefault();
      var name = dot.getAttribute('data-fixture') || 'seed';
      window.hrOpenDataset(name === 'seed' ? '' : name);
    };
    document.addEventListener('click', onDot, true);
    document.addEventListener('keydown', onDot, true);
  }

  // The caption over the trace shot links to the pair of the test that trace belongs to,
  // and that pair is shut: a link to a shut fold scrolls to its one-line summary and stops,
  // which leaves the reader one click short of the diagram they were told to compare. Opened
  // here, before the browser follows the link, so the scroll lands on the open pair.
  document.addEventListener('click', function (ev) {
    var link = ev.target.closest && ev.target.closest('.seqhow-cap a[href^="#"]');
    if (!link) return;
    var pair = document.getElementById(decodeURIComponent(link.getAttribute('href').slice(1)));
    if (pair && pair.tagName === 'DETAILS') pair.open = true;
  });
})();
