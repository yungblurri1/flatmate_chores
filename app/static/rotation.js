/* The rotation kernel, mirroring app/rotation.py and app/stats.py.
 *
 * The browser needs to compute a roster for any week without asking the server,
 * which means this logic exists twice. It is kept in its own file, with no DOM or
 * app state touched, so tests/test_js_parity.py can run it under Node and assert
 * it agrees with the Python line for line. Python stays the reference: change it
 * there first, then here, and the parity test will tell you if they drifted.
 */
(function (root) {
  'use strict';

  var WEEK_MS = 604800000;
  var EPOCH_MONDAY = Date.UTC(2024, 0, 1); // 2024-01-01 was a Monday
  var EPOCH_YEAR = 2024;

  function parseDate(iso) {
    var p = iso.split('-').map(Number);
    return new Date(p[0], p[1] - 1, p[2]);
  }

  // Compare days as UTC midnights so a DST shift can never move a date by a day.
  function utcMidnight(d) {
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  }

  function addDays(d, n) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  }

  function mondayOf(d) {
    return addDays(d, -((d.getDay() + 6) % 7)); // getDay(): 0 = Sunday
  }

  function weekIndex(d) {
    return Math.round((utcMidnight(mondayOf(d)) - EPOCH_MONDAY) / WEEK_MS);
  }

  function monthIndex(d) {
    return (d.getFullYear() - EPOCH_YEAR) * 12 + d.getMonth();
  }

  function periodIndex(d, frequency) {
    return frequency === 'weekly' ? weekIndex(d) : monthIndex(d);
  }

  function periodKeyFor(d, frequency) {
    return frequency === 'weekly' ? 'W-' + weekIndex(d) : 'M-' + monthIndex(d);
  }

  function weekBounds(d) {
    var monday = mondayOf(d);
    return [monday, addDays(monday, 6)];
  }

  function progressKey(taskId, periodKey) {
    return taskId + '|' + periodKey;
  }

  function assignmentsFor(day, people, tasks) {
    if (!people.length) return [];
    var n = people.length;
    var out = [];

    tasks.forEach(function (task) {
      var pi = periodIndex(day, task.frequency);
      var key = periodKeyFor(day, task.frequency);

      // A one-off exists in exactly one period and nowhere else.
      if (task.periodKey && task.periodKey !== key) return;
      // Nothing exists before the chore did.
      if (task.startsOn && pi < periodIndex(parseDate(task.startsOn), task.frequency)) return;

      out.push({
        task: task,
        person: people[(((pi + task.slot) % n) + n) % n],
        periodKey: key
      });
    });

    return out;
  }

  function firstOfMonthOffset(today, monthsAgo) {
    var total = today.getMonth() - monthsAgo;
    return new Date(today.getFullYear() + Math.floor(total / 12), ((total % 12) + 12) % 12, 1);
  }

  /** Mirrors stats.missed_by_person: only fully-elapsed periods count. */
  function missedByPerson(people, tasks, done, reassigned, range, today) {
    var past = new Map();
    var i;

    function collect(day, frequency) {
      assignmentsFor(day, people, tasks).forEach(function (a) {
        if (a.task.frequency !== frequency) return;
        past.set(progressKey(a.task.id, a.periodKey), a);
      });
    }

    for (i = 1; i <= range.weeks; i++) collect(addDays(today, -7 * i), 'weekly');
    for (i = 1; i <= range.months; i++) collect(firstOfMonthOffset(today, i), 'monthly');

    var missed = {};
    people.forEach(function (p) { missed[p] = 0; });
    past.forEach(function (a, key) {
      if (done.has(key)) return;
      var person = Object.prototype.hasOwnProperty.call(reassigned, key)
        ? reassigned[key]
        : a.person;
      if (person in missed) missed[person] += 1;
    });
    return missed;
  }

  root.Rotation = {
    parseDate: parseDate,
    addDays: addDays,
    weekIndex: weekIndex,
    monthIndex: monthIndex,
    periodIndex: periodIndex,
    periodKeyFor: periodKeyFor,
    weekBounds: weekBounds,
    progressKey: progressKey,
    assignmentsFor: assignmentsFor,
    missedByPerson: missedByPerson
  };
})(typeof module !== 'undefined' && module.exports ? module.exports : window);
