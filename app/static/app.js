/* Flatmate Chores -- client-side app.
 *
 * The server hands over the whole state once (see #initial-state) and this file
 * does the rest: it recomputes the roster for any week locally, so changing week,
 * switching the slacking range, and opening the manage view all happen with no
 * network at all. Only saving a change makes a request, and the local state is
 * updated first so the UI never waits on it.
 *
 * The rotation maths lives in rotation.js, which mirrors the Python and is parity
 * tested against it. This file is views and wiring only.
 */
(function () {
  'use strict';

  var STATE = JSON.parse(document.getElementById('initial-state').textContent);
  STATE.done = new Set(STATE.done);

  // STATE.ranges is an ordered list; this is the by-key lookup alongside it.
  var RANGE_BY_KEY = {};
  STATE.ranges.forEach(function (r) { RANGE_BY_KEY[r.key] = r; });

  var parseDate = Rotation.parseDate;
  var addDays = Rotation.addDays;
  var weekIndex = Rotation.weekIndex;
  var periodIndex = Rotation.periodIndex;
  var periodKeyFor = Rotation.periodKeyFor;
  var weekBounds = Rotation.weekBounds;
  var progressKey = Rotation.progressKey;
  var assignmentsFor = Rotation.assignmentsFor;

  // ------------------------------------------------------------------ state

  var TODAY = parseDate(STATE.today); // the server's date, so it matches the DB

  var view = location.pathname === '/chores' ? 'manage' : 'roster';
  var weekOffset = Number(new URLSearchParams(location.search).get('week_offset')) || 0;
  var rangeKey = new URLSearchParams(location.search).get('range') || STATE.defaultRange;
  if (!RANGE_BY_KEY[rangeKey]) rangeKey = STATE.defaultRange;
  var editing = false;
  var chart = null;

  function viewedDay() {
    return addDays(TODAY, weekOffset * 7);
  }

  // ------------------------------------------------------------------ theme

  /* Three states, not two: "auto" follows the device, and losing it the moment
   * you touch the button would be a one-way door. Only an explicit choice is
   * stored, so a device that later switches to dark still gets dark. */
  var THEMES = [
    { key: 'auto', icon: '◐', label: 'Auto' },
    { key: 'light', icon: '☀', label: 'Light' },
    { key: 'dark', icon: '☾', label: 'Dark' }
  ];

  function storedTheme() {
    var saved = null;
    try { saved = localStorage.getItem('theme'); } catch (e) { /* private mode */ }
    return saved === 'light' || saved === 'dark' ? saved : 'auto';
  }

  function applyTheme(key) {
    if (key === 'auto') {
      document.documentElement.removeAttribute('data-theme');
      try { localStorage.removeItem('theme'); } catch (e) { /* ignore */ }
    } else {
      document.documentElement.setAttribute('data-theme', key);
      try { localStorage.setItem('theme', key); } catch (e) { /* ignore */ }
    }
  }

  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)');

  /** What is actually on screen right now, whichever way it was decided. */
  function isDark() {
    var explicit = document.documentElement.getAttribute('data-theme');
    if (explicit) return explicit === 'dark';
    return prefersDark.matches;
  }

  /** Person colours are stepped per surface, so they switch with the theme. */
  function colorOf(person) {
    var palette = isDark() ? STATE.colorsDark : STATE.colors;
    return palette[person] || '#9aa5a1';
  }

  /** Read a theme token, so the canvas can be painted from the same source. */
  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  /** Assignments for `day`, with reassignments and tick state folded in. */
  function rowsFor(day) {
    return assignmentsFor(day, STATE.people, STATE.tasks).map(function (a) {
      var key = progressKey(a.task.id, a.periodKey);
      var person = Object.prototype.hasOwnProperty.call(STATE.reassigned, key)
        ? STATE.reassigned[key]
        : a.person;
      return { task: a.task, person: person, periodKey: a.periodKey, done: STATE.done.has(key) };
    });
  }

  function missedByPerson(key) {
    return Rotation.missedByPerson(
      STATE.people, STATE.tasks, STATE.done, STATE.reassigned,
      RANGE_BY_KEY[key] || RANGE_BY_KEY[STATE.defaultRange], TODAY
    );
  }

  function recurring(frequency) {
    return STATE.tasks.filter(function (t) {
      return !t.periodKey && t.frequency === frequency;
    });
  }

  /** Who a recurring chore lands on in the current period -- its "starter". */
  function starterOf(task) {
    if (!STATE.people.length) return null;
    var pi = periodIndex(TODAY, task.frequency);
    var n = STATE.people.length;
    return STATE.people[(((pi + task.slot) % n) + n) % n];
  }

  // ------------------------------------------------------------------- api

  function api(method, url, body) {
    return fetch(url, {
      method: method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined
    }).then(function (res) {
      if (!res.ok) throw new Error(method + ' ' + url + ' -> ' + res.status);
      return res.status === 204 ? null : res.json();
    });
  }

  /* Ticking a chore off plays static/sounds/done.mp3 if it is there. One Audio
   * object, rewound each time, so ticking several chores quickly re-triggers
   * instead of queueing. play() rejects when the browser blocks autoplay -- a
   * click counts as a gesture so it normally will not, and a missing noise is
   * never worth an error. */
  var doneSound = null;

  function playDoneSound() {
    if (!STATE.sounds.done) return;
    if (!doneSound) doneSound = new Audio(STATE.sounds.done);
    doneSound.currentTime = 0;
    var played = doneSound.play();
    if (played && played.catch) played.catch(function () { /* blocked or no file */ });
  }

  /** Styled stand-in for confirm(). Resolves true only if Delete was pressed. */
  function askDelete(name) {
    var dialog = document.getElementById('confirm-dialog');
    document.getElementById('confirm-text').textContent =
      '“' + name + '” and everything ticked off for it will be removed. ' +
      'This cannot be undone.';

    return new Promise(function (resolve) {
      dialog.returnValue = 'cancel'; // Esc and backdrop dismissals land here
      dialog.addEventListener('close', function onClose() {
        dialog.removeEventListener('close', onClose);
        resolve(dialog.returnValue === 'ok');
      });
      dialog.showModal();
    });
  }

  /** A save failed, so local state may now disagree with the server. Reload. */
  function saveFailed(err) {
    console.error(err);
    alert('Could not save that change. Reloading to get back in sync.');
    location.reload();
  }

  // -------------------------------------------------------------- rendering

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];

  function shortDate(d) {
    return d.getDate() + ' ' + MONTHS[d.getMonth()].slice(0, 3);
  }

  /** "3 weeks ago" / "in 2 weeks" -- how far the view is from the current week. */
  function weeksAway() {
    var n = Math.abs(weekOffset);
    var unit = n === 1 ? 'week' : 'weeks';
    return weekOffset < 0 ? n + ' ' + unit + ' ago' : 'in ' + n + ' ' + unit;
  }

  function personOptions(selected) {
    return STATE.people.map(function (p) {
      return '<option value="' + esc(p) + '"' + (p === selected ? ' selected' : '') + '>' + esc(p) + '</option>';
    }).join('');
  }

  /** A person's marker: their portrait if static/faces has one, else a dot.
   *
   * Either way it carries their colour -- as the fill, or as a ring round the
   * photo -- so the colour coding still holds when only some people have a face. */
  function dot(person) {
    var color = esc(colorOf(person));
    if (STATE.faces[person]) {
      return '<img class="face" src="' + esc(STATE.faces[person]) + '" alt=""' +
        ' style="border-color:' + color + '">';
    }
    return '<span class="dot" style="background:' + color + '"></span>';
  }

  function cardHtml(row) {
    var t = row.task;
    var unit = t.frequency === 'weekly' ? 'week' : 'month';
    return '' +
      '<article class="card' + (t.frequency === 'monthly' ? ' monthly' : '') +
        (row.done ? ' is-done' : '') + (t.periodKey ? ' is-oneoff' : '') + '">' +
        '<button class="delete-btn" data-act="delete" data-id="' + esc(t.id) + '"' +
          ' title="Delete chore" aria-label="Delete ' + esc(t.name) + '">&times;</button>' +
        '<div class="card-body">' +
          '<h3 class="task-name">' + esc(t.name) + '</h3>' +
          (t.periodKey ? '<span class="badge-oneoff">This ' + unit + ' only</span>' : '') +
          (t.description ? '<p class="task-desc">' + esc(t.description) + '</p>' : '') +
        '</div>' +
        '<div class="card-foot">' +
          '<span class="reassign">' + dot(row.person) +
            '<select class="person-select" data-act="reassign" data-id="' + esc(t.id) +
              '" data-period="' + esc(row.periodKey) + '" aria-label="Reassign ' + esc(t.name) + '">' +
              personOptions(row.person) +
            '</select>' +
          '</span>' +
          '<button class="check' + (row.done ? ' checked' : '') + '" data-act="toggle"' +
            ' data-id="' + esc(t.id) + '" data-period="' + esc(row.periodKey) + '"' +
            ' data-person="' + esc(row.person) + '" data-done="' + (row.done ? '1' : '0') + '">' +
            (row.done ? 'Done' : 'Mark done') +
          '</button>' +
        '</div>' +
      '</article>';
  }

  var REPO = 'https://github.com/yungblurri1/flatmate_chores';

  /* The year comes from the clock rather than being typed in, so the notice does
   * not quietly go stale next January. External link, so no data-act -- the SPA
   * router only intercepts its own. */
  function footerHtml(note) {
    return '<footer class="foot">' +
      (note ? '<p class="foot-note">' + note + '</p>' : '') +
      '<p class="foot-legal">&copy; ' + new Date().getFullYear() + ' yungblurri1 &middot; ' +
        '<a href="' + REPO + '" target="_blank" rel="noopener noreferrer">' +
        'flatmate_chores on GitHub</a></p>' +
    '</footer>';
  }

  function themeButtonHtml() {
    var current = THEMES.filter(function (t) { return t.key === storedTheme(); })[0];
    return '<button class="tool-btn theme-btn" data-act="theme"' +
      ' aria-label="Colour theme: ' + current.label + '. Click to change."' +
      ' title="Theme: ' + current.label + '">' +
      '<span class="theme-icon" aria-hidden="true">' + current.icon + '</span>' +
      current.label + '</button>';
  }

  function addTileHtml(frequency) {
    var unit = frequency === 'weekly' ? 'week' : 'month';
    return '' +
      '<article class="card card-add">' +
        '<button type="button" class="add-open" data-act="open-add"' +
          ' aria-label="Add a chore to this ' + unit + ' only">+</button>' +
        '<form class="add-form" data-act="add-oneoff" data-frequency="' + frequency + '">' +
          '<input class="add-input" name="name" required maxlength="60"' +
            ' placeholder="Chore for this ' + unit + '" aria-label="Chore name">' +
          '<input class="add-input" name="description" maxlength="140"' +
            ' placeholder="Description (optional)" aria-label="Description">' +
          '<button type="submit" class="add-btn">Add to this ' + unit + ' only</button>' +
        '</form>' +
      '</article>';
  }

  function boardHtml(rows, frequency) {
    return rows.filter(function (r) { return r.task.frequency === frequency; })
      .map(cardHtml).join('') + addTileHtml(frequency);
  }

  // ------------------------------------------------------------ roster view

  var barValueLabels = {
    id: 'barValueLabels',
    afterDatasetsDraw: function (c) {
      var ctx = c.ctx;
      var ink = token('--ink'); // read per draw, so it follows a theme switch
      c.getDatasetMeta(0).data.forEach(function (bar, i) {
        ctx.save();
        ctx.fillStyle = ink;
        ctx.font = '600 13px -apple-system, BlinkMacSystemFont, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(c.data.datasets[0].data[i], bar.x + 8, bar.y);
        ctx.restore();
      });
    }
  };

  function mountRoster() {
    document.getElementById('app').innerHTML = '' +
      '<main class="page">' +
        '<header class="masthead">' +
          '<div class="masthead-title">' +
            '<span class="eyebrow">House Chores</span>' +
            '<h1>' + esc(STATE.householdName) + '</h1>' +
          '</div>' +
          '<div class="masthead-tools">' +
            '<div class="roster-strip" id="roster-strip"></div>' +
            '<div class="tool-row">' +
              themeButtonHtml() +
              '<button class="tool-btn" id="edit-btn" data-act="toggle-edit">Edit</button>' +
              '<a class="tool-btn" href="/chores" data-act="nav">Manage chores</a>' +
            '</div>' +
          '</div>' +
        '</header>' +
        (STATE.images.length
          ? '<figure class="hero" id="hero">' +
              '<img id="hero-img" alt="" draggable="false">' +
              '<div class="hero-handle" id="hero-handle" role="separator" tabindex="0"' +
                ' aria-label="Resize the banner. Drag, or double-click to fit the whole picture."' +
                ' title="Drag to resize · double-click to fit the whole picture">' +
                '<span class="hero-grip"></span>' +
              '</div>' +
            '</figure>'
          : '') +
        '<nav class="weeknav">' +
          '<button class="weeknav-btn" data-act="week" data-delta="-1">&lsaquo; Prev</button>' +
          '<div class="weeknav-label" id="weeknav-label"></div>' +
          '<button class="weeknav-btn" data-act="week" data-delta="1">Next &rsaquo;</button>' +
        '</nav>' +
        '<section class="board">' +
          '<div class="board-head"><h2>Weekly</h2>' +
            '<span class="board-sub">Rotates every Monday</span></div>' +
          '<div class="cards" id="weekly-cards"></div>' +
        '</section>' +
        '<section class="board">' +
          '<div class="board-head"><h2>Monthly</h2>' +
            '<span class="board-sub" id="month-label"></span></div>' +
          '<div class="cards" id="monthly-cards"></div>' +
        '</section>' +
        '<section class="board">' +
          '<div class="board-head"><h2>Who\'s slacking</h2>' +
            '<span class="board-sub">Assigned chores left undone once their period closed</span></div>' +
          '<div class="range-picker" id="range-picker"></div>' +
          '<div class="chart-wrap"><canvas id="missed-chart"></canvas></div>' +
        '</section>' +
        footerHtml(
          'Assignments are computed from the date. <strong>Edit</strong> adds one-off chores ' +
          'to a single week or month; <strong>Manage chores</strong> changes the ones that repeat.'
        ) +
      '</main>';

    chart = new Chart(document.getElementById('missed-chart'), {
      type: 'bar',
      data: {
        labels: [],
        datasets: [{
          label: 'Missed chores',
          data: [],
          backgroundColor: [],
          borderRadius: 4,      // rounded data-end, square against the baseline
          maxBarThickness: 34
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        animation: { duration: 200 },
        layout: { padding: { right: 30 } },
        // One series, and the y-axis already names each person, so a legend would
        // only repeat what the axis says.
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: token('--ink'),
            titleColor: token('--surface'),
            bodyColor: token('--surface'),
            padding: 10,
            cornerRadius: 8,
            displayColors: false,
            callbacks: {
              label: function (c) {
                return c.parsed.x === 1 ? '1 chore missed' : c.parsed.x + ' chores missed';
              }
            }
          }
        },
        scales: {
          x: {
            beginAtZero: true,
            grace: '15%',
            border: { display: false },
            grid: { color: token('--grid'), drawTicks: false },
            ticks: { precision: 0, color: token('--muted'), padding: 6 }
          },
          y: {
            border: { display: false },
            grid: { display: false },
            ticks: { color: token('--ink'), font: { weight: '600', size: 13 } }
          }
        }
      },
      plugins: [barValueLabels]
    });

    setUpHeroResize();

    // Edit mode survives navigating away to the manage view and back.
    var editBtn = document.getElementById('edit-btn');
    editBtn.textContent = editing ? 'Done editing' : 'Edit';
    editBtn.classList.toggle('active', editing);
    document.body.classList.toggle('is-editing', editing);

    refreshRoster();
  }

  var HERO_MIN = 76;

  function heroMax() {
    return Math.round(window.innerHeight * 0.85);
  }

  function setHeroHeight(px) {
    var hero = document.getElementById('hero');
    if (!hero) return;
    var h = Math.max(HERO_MIN, Math.min(heroMax(), Math.round(px)));
    hero.style.height = h + 'px';
    try { localStorage.setItem('heroHeight', String(h)); } catch (e) { /* private mode */ }
  }

  /* Drag-to-resize the banner.
   *
   * Hand-rolled rather than CSS `resize` because that puts its grip in the
   * bottom-right corner (not the bottom edge, where a banner wants it), offers no
   * way to style or label it, and does nothing at all on touch. Pointer events
   * cover mouse, pen and finger in one path. */
  function setUpHeroResize() {
    var hero = document.getElementById('hero');
    var handle = document.getElementById('hero-handle');
    if (!hero || !handle) return;

    var saved = null;
    try { saved = localStorage.getItem('heroHeight'); } catch (e) { /* private mode */ }
    if (saved) hero.style.height = Math.max(HERO_MIN, Math.min(heroMax(), Number(saved))) + 'px';

    handle.addEventListener('pointerdown', function (event) {
      event.preventDefault(); // else the browser starts dragging the image
      var startY = event.clientY;
      var startH = hero.getBoundingClientRect().height;
      handle.setPointerCapture(event.pointerId);

      function onMove(moveEvent) {
        setHeroHeight(startH + (moveEvent.clientY - startY));
      }
      function onUp() {
        handle.releasePointerCapture(event.pointerId);
        handle.removeEventListener('pointermove', onMove);
        handle.removeEventListener('pointerup', onUp);
        handle.removeEventListener('pointercancel', onUp);
      }

      handle.addEventListener('pointermove', onMove);
      handle.addEventListener('pointerup', onUp);
      handle.addEventListener('pointercancel', onUp);
    });

    // Double-click: snap between the thin banner and the whole picture.
    handle.addEventListener('dblclick', function () {
      var img = document.getElementById('hero-img');
      var natural = img.naturalWidth
        ? hero.clientWidth * (img.naturalHeight / img.naturalWidth)
        : 132;
      var full = Math.min(heroMax(), natural);
      setHeroHeight(hero.getBoundingClientRect().height >= full - 2 ? 132 : full);
    });

    // Keyboard: the handle is focusable, so it must be operable too.
    handle.addEventListener('keydown', function (event) {
      var step = event.key === 'ArrowUp' ? -24 : event.key === 'ArrowDown' ? 24 : 0;
      if (!step) return;
      event.preventDefault();
      setHeroHeight(hero.getBoundingClientRect().height + step);
    });
  }

  function refreshRoster() {
    var day = viewedDay();
    var rows = rowsFor(day);
    var bounds = weekBounds(day);

    var load = {};
    STATE.people.forEach(function (p) { load[p] = 0; });
    rows.forEach(function (r) {
      if (r.task.frequency === 'weekly' && r.person in load) load[r.person] += 1;
    });

    document.getElementById('roster-strip').innerHTML = STATE.people.map(function (p) {
      return '<span class="chip">' + dot(p) + esc(p) +
        '<span class="chip-load">' + load[p] + '</span></span>';
    }).join('');

    document.getElementById('weeknav-label').innerHTML =
      '<strong>' + shortDate(bounds[0]) + ' &ndash; ' + shortDate(bounds[1]) + '</strong>' +
      (weekOffset === 0
        ? '<span class="badge-now">This week</span>'
        : '<button class="badge-back" data-act="today">' + esc(weeksAway()) +
          ' &middot; back to this week</button>');
    document.body.classList.toggle('is-other-week', weekOffset !== 0);

    document.getElementById('month-label').textContent =
      MONTHS[day.getMonth()] + ' ' + day.getFullYear();

    // One picture per week, in order, wrapping round. A single file just stays put.
    if (STATE.images.length) {
      var n = STATE.images.length;
      var src = STATE.images[((weekIndex(day) % n) + n) % n];
      var img = document.getElementById('hero-img');
      if (img.getAttribute('src') !== src) img.src = src;
    }

    document.getElementById('weekly-cards').innerHTML = boardHtml(rows, 'weekly');
    document.getElementById('monthly-cards').innerHTML = boardHtml(rows, 'monthly');

    refreshChart();
    syncUrl();
  }

  function refreshChart() {
    document.getElementById('range-picker').innerHTML = STATE.ranges.map(function (r) {
      return '<button class="range-pill' + (r.key === rangeKey ? ' active' : '') + '"' +
        ' data-act="range" data-range="' + esc(r.key) + '">' + esc(r.label) + '</button>';
    }).join('');

    var missed = missedByPerson(rangeKey);
    var labels = STATE.people.slice().sort(function (a, b) { return missed[b] - missed[a]; });

    chart.data.labels = labels;
    chart.data.datasets[0].data = labels.map(function (p) { return missed[p]; });
    chart.data.datasets[0].backgroundColor = labels.map(colorOf);
    chart.update();
  }

  function syncUrl() {
    var q = new URLSearchParams();
    if (weekOffset) q.set('week_offset', weekOffset);
    if (rangeKey !== STATE.defaultRange) q.set('range', rangeKey);
    var s = q.toString();
    history.replaceState({}, '', '/' + (s ? '?' + s : ''));
  }

  // ------------------------------------------------------------ manage view

  function mountManage() {
    document.body.classList.remove('is-editing'); // edit mode is a roster thing
    document.getElementById('app').innerHTML = '' +
      '<main class="page">' +
        '<header class="masthead">' +
          '<div class="masthead-title">' +
            '<span class="eyebrow">Repeating chores</span>' +
            '<h1>Manage chores</h1>' +
          '</div>' +
          '<div class="tool-row">' +
            '<a class="tool-btn" href="/" data-act="nav">&lsaquo; Back to the roster</a>' +
          '</div>' +
        '</header>' +
        '<p class="manage-intro">These repeat forever, rotating through everyone. ' +
          'Pick who starts and the rest follow in order. Chores added here begin ' +
          'today &mdash; earlier weeks stay untouched.</p>' +
        manageSectionHtml('weekly', 'Weekly', 'Rotates every Monday') +
        manageSectionHtml('monthly', 'Monthly', 'Rotates on the 1st') +
        footerHtml('') +
      '</main>';
  }

  function manageSectionHtml(frequency, heading, sub) {
    var tasks = recurring(frequency);
    var rows = tasks.length
      ? tasks.map(manageRowHtml).join('')
      : '<p class="board-sub empty-note">No ' + frequency + ' chores yet.</p>';

    return '' +
      '<section class="board">' +
        '<div class="board-head"><h2>' + heading + '</h2>' +
          '<span class="board-sub">' + sub + '</span></div>' +
        '<div class="manage-list">' + rows + '</div>' +
        '<form class="manage-add" data-act="add-recurring" data-frequency="' + frequency + '">' +
          '<input class="add-input" name="name" required maxlength="60"' +
            ' placeholder="New ' + frequency + ' chore" aria-label="New ' + frequency + ' chore">' +
          '<input class="add-input" name="description" maxlength="140"' +
            ' placeholder="Description (optional)" aria-label="Description">' +
          '<label class="starter-field">Starts with' +
            '<select name="starter" class="person-select">' +
              '<option value="">Next in rotation</option>' + personOptions(null) +
            '</select>' +
          '</label>' +
          '<button type="submit" class="add-btn">Add</button>' +
        '</form>' +
      '</section>';
  }

  function manageRowHtml(task) {
    return '' +
      '<div class="manage-row">' +
        '<div class="manage-main">' +
          '<span class="manage-name">' + esc(task.name) + '</span>' +
          (task.description ? '<span class="task-desc">' + esc(task.description) + '</span>' : '') +
        '</div>' +
        '<label class="starter-field">Starts with' +
          '<span class="reassign">' + dot(starterOf(task)) +
            '<select class="person-select" data-act="starter" data-id="' + esc(task.id) + '"' +
              ' aria-label="Who starts ' + esc(task.name) + '">' +
              personOptions(starterOf(task)) +
            '</select>' +
          '</span>' +
        '</label>' +
        '<button class="row-delete" data-act="delete" data-id="' + esc(task.id) + '"' +
          ' aria-label="Delete ' + esc(task.name) + '">Delete</button>' +
      '</div>';
  }

  // ---------------------------------------------------------------- actions

  function forgetTaskLocally(id) {
    STATE.tasks = STATE.tasks.filter(function (t) { return t.id !== id; });
    Array.from(STATE.done).forEach(function (k) {
      if (k.indexOf(id + '|') === 0) STATE.done.delete(k);
    });
    Object.keys(STATE.reassigned).forEach(function (k) {
      if (k.indexOf(id + '|') === 0) delete STATE.reassigned[k];
    });
  }

  function rerender() {
    if (view === 'manage') mountManage(); else refreshRoster();
  }

  var ACTIONS = {
    week: function (el) {
      weekOffset += Number(el.dataset.delta);
      refreshRoster();
    },

    today: function () {
      weekOffset = 0;
      refreshRoster();
    },

    theme: function () {
      var next = THEMES[(THEMES.map(function (t) { return t.key; }).indexOf(storedTheme()) + 1) % THEMES.length];
      applyTheme(next.key);
      route(); // remount so person colours and the chart re-read the new tokens
    },

    range: function (el) {
      rangeKey = el.dataset.range;
      refreshChart();
      syncUrl();
    },

    'toggle-edit': function () {
      editing = !editing;
      document.body.classList.toggle('is-editing', editing);
      document.getElementById('edit-btn').textContent = editing ? 'Done editing' : 'Edit';
      document.getElementById('edit-btn').classList.toggle('active', editing);
    },

    'open-add': function (el) {
      el.parentNode.classList.add('is-open');
      var input = el.parentNode.querySelector('input[name="name"]');
      if (input) input.focus();
    },

    toggle: function (el) {
      var done = el.dataset.done !== '1';
      var key = progressKey(el.dataset.id, el.dataset.period);
      if (done) STATE.done.add(key); else STATE.done.delete(key);
      if (done) playDoneSound(); // only the reward, not the undo
      rerender();
      api('POST', '/api/completions', {
        task_id: el.dataset.id,
        period_key: el.dataset.period,
        done: done,
        person: el.dataset.person
      }).catch(saveFailed);
    },

    delete: function (el) {
      var id = el.dataset.id;
      var task = STATE.tasks.find(function (t) { return t.id === id; });
      askDelete(task ? task.name : 'This chore').then(function (confirmed) {
        if (!confirmed) return;
        forgetTaskLocally(id);
        rerender();
        api('DELETE', '/api/tasks/' + encodeURIComponent(id)).catch(saveFailed);
      });
    },

    reassign: function (el) {
      STATE.reassigned[progressKey(el.dataset.id, el.dataset.period)] = el.value;
      rerender();
      api('POST', '/api/reassignments', {
        task_id: el.dataset.id,
        period_key: el.dataset.period,
        person: el.value
      }).catch(saveFailed);
    },

    starter: function (el) {
      api('PATCH', '/api/tasks/' + encodeURIComponent(el.dataset.id), { starter: el.value })
        .then(function (task) {
          var i = STATE.tasks.findIndex(function (t) { return t.id === task.id; });
          if (i >= 0) STATE.tasks[i] = task;
          rerender();
        })
        .catch(saveFailed);
    },

    'add-oneoff': function (form) {
      var name = form.elements.name.value.trim();
      if (!name) return;
      api('POST', '/api/tasks', {
        name: name,
        frequency: form.dataset.frequency,
        description: form.elements.description.value.trim(),
        period_key: periodKeyFor(viewedDay(), form.dataset.frequency)
      }).then(function (task) {
        STATE.tasks.push(task);
        refreshRoster();
      }).catch(saveFailed);
      form.reset();
    },

    'add-recurring': function (form) {
      var name = form.elements.name.value.trim();
      if (!name) return;
      api('POST', '/api/tasks', {
        name: name,
        frequency: form.dataset.frequency,
        description: form.elements.description.value.trim(),
        starter: form.elements.starter.value || null
      }).then(function (task) {
        STATE.tasks.push(task);
        mountManage();
      }).catch(saveFailed);
      form.reset();
    }
  };

  // ------------------------------------------------------------------ wiring

  var app = document.getElementById('app');

  app.addEventListener('click', function (event) {
    var el = event.target.closest('[data-act]');
    if (!el || el.tagName === 'SELECT' || el.tagName === 'FORM') return;

    if (el.dataset.act === 'nav') {
      event.preventDefault();
      navigate(el.getAttribute('href'));
      return;
    }
    var handler = ACTIONS[el.dataset.act];
    if (handler) { event.preventDefault(); handler(el); }
  });

  app.addEventListener('change', function (event) {
    var el = event.target.closest('select[data-act]');
    if (el && ACTIONS[el.dataset.act]) ACTIONS[el.dataset.act](el);
  });

  app.addEventListener('submit', function (event) {
    var form = event.target.closest('form[data-act]');
    if (!form || !ACTIONS[form.dataset.act]) return;
    event.preventDefault();
    ACTIONS[form.dataset.act](form);
  });

  function navigate(path) {
    history.pushState({}, '', path);
    route();
  }

  function route() {
    view = location.pathname === '/chores' ? 'manage' : 'roster';
    if (view === 'manage') mountManage(); else mountRoster();
  }

  window.addEventListener('popstate', route);

  // On "auto", follow the device if it flips mid-session (e.g. at sunset).
  var onSchemeChange = function () { if (storedTheme() === 'auto') route(); };
  if (prefersDark.addEventListener) prefersDark.addEventListener('change', onSchemeChange);
  else if (prefersDark.addListener) prefersDark.addListener(onSchemeChange); // older Safari

  route();
})();
