// Every film's captions, wired once at load and again over whatever a rebuild swaps in
// (`hr:swapped`, a tab's panel from `panels.js` or a card from `rerun.js`): the new
// markup arrives with none of the listeners below.
(function () {
function wire(root) {
root.querySelectorAll('.vidwrap').forEach(function (wrap) {
  var video = wrap.querySelector('video');
  var items = Array.prototype.slice.call(wrap.querySelectorAll('.transcript li[data-t]'));
  if (!items.length) return;
  // A run that failed to record still ships the transcript, with a notice where the player
  // would be. There is nothing to seek, so the captions stay plain text — and nothing here
  // may throw, or the scripts after it never run.
  if (!video) return;

  // Where each caption starts in the film being played. Each voice is its own cut of the
  // take (a slower voice holds every shot longer), so its radio carries its own cue times
  // in data-ts; a film without them shares the transcript clock.
  var clock = items.map(function (li) { return parseFloat(li.dataset.t); });
  var timesOf = function (radio) {
    var ts = (radio.dataset.ts || '').split(',').map(parseFloat);
    return ts.length === items.length && !ts.some(isNaN) ? ts : clock;
  };
  var cueAt = function (t) {
    var i = -1;
    clock.forEach(function (c, k) { if (c <= t) i = k; });
    return i;
  };
  var showTimes = function () {
    items.forEach(function (li, k) {
      var s = li.querySelector('.ts'), t = Math.floor(clock[k]);
      if (s) s.textContent = Math.floor(t / 60) + ':' + ('0' + t % 60).slice(-2);
    });
  };

  // The voice switch: the same take in another voice, one radio button per film. The swap
  // lands on the same caption, as far into it as the reader was, and playing stays
  // playing. The choice is remembered per browser — whoever picked a voice once wants it
  // on the next review too.
  // It sits in the Running app row above this wrap (under the player only when there is
  // no row), so it is found by what it switches, not by where it is: the group whose
  // standard radio plays this film's own src.
  var src = video.getAttribute('src');
  var group = Array.prototype.filter.call(
    (wrap.closest('.panel') || document).querySelectorAll('.voice-switch'), function (g) {
      var std = g.querySelector('input[value=""]');
      return std && std.dataset.src === src;
    })[0];
  var radios = group ? Array.prototype.slice.call(group.querySelectorAll('input')) : [];
  if (radios.length) {
    var swap = function (radio) {
      var t = video.currentTime, playing = !video.paused;
      var next = timesOf(radio), i = cueAt(t);
      if (i >= 0) {
        var end = i + 1 < next.length ? next[i + 1] : Infinity;
        t = Math.min(next[i] + (t - clock[i]), end - 0.05);
      }
      clock = next;
      showTimes();
      video.src = radio.dataset.src;
      video.addEventListener('loadedmetadata', function once() {
        video.removeEventListener('loadedmetadata', once);
        video.currentTime = t;
        if (playing) video.play();
      });
      try { localStorage.setItem('hr-voice', radio.value); } catch (e) {}
    };
    radios.forEach(function (r) {
      r.addEventListener('change', function () { if (r.checked) swap(r); });
    });
    try {
      // 'hr-cloned-voice' is what the old 🐘 checkbox remembered.
      var kept = localStorage.getItem('hr-voice');
      if (kept === null && localStorage.getItem('hr-cloned-voice')) kept = 'trump';
      var pick = kept && radios.filter(function (r) { return r.value === kept; })[0];
      if (pick) { pick.checked = true; swap(pick); }
    } catch (e) {}
  }
  items.forEach(function (li) {
    li.addEventListener('click', function (ev) {
      // Captions carry links to the pages they describe. A click on one opens that page
      // and nothing else — seeking as well would yank the video out from under a reader
      // who was only following the link.
      if (ev.target.closest && ev.target.closest('a, .cue-drive')) return;
      // Seek, and stop there. Clicking a caption is how a reader *finds* a moment — often
      // one they want to look at, or read around, before watching. Starting playback on
      // that click takes the decision away from them and starts talking; the same rule
      // that keeps the film paused when the tab opens applies to every click after it.
      // The play button is right there, and the frame they asked for is now under it.
      // Seeking alone keeps whatever state the video was in: paused stays paused, and a
      // film already running keeps running from the new point.
      video.currentTime = clock[items.indexOf(li)];
    });
  });

  // It does NOT play on arrival. A film that starts talking the moment a tab opens
  // interrupts the reader instead of serving them — they may be here for the transcript,
  // or reading with someone next to them. The play button is right there.
  // Leaving the tab still pauses it: sound following you to another tab is worse.
  var panel = wrap.closest && wrap.closest('.panel');
  if (panel) {
    panel.addEventListener('panelhide', function () { video.pause(); });
  }
  video.addEventListener('timeupdate', function () {
    var active = null;
    var i = cueAt(video.currentTime);
    if (i >= 0) active = items[i];
    items.forEach(function (li) { li.classList.toggle('on', li === active); });
    if (!active) return;
    // Measured against the panel's own box: offsetTop is relative to the nearest
    // positioned ancestor, which is not necessarily the scroller.
    var panel = active.parentNode;
    var a = active.getBoundingClientRect();
    var p = panel.getBoundingClientRect();
    if (a.top < p.top) panel.scrollTop += a.top - p.top - 8;
    else if (a.bottom > p.bottom) panel.scrollTop += a.bottom - p.bottom + 8;
  });
});
}
wire(document);
document.addEventListener('hr:swapped', function (ev) {
  if (ev.detail && ev.detail.querySelectorAll) wire(ev.detail);
});
})();
