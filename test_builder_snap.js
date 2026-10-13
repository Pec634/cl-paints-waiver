/* Run with node test_builder_snap.js; the same suite can run in a JS isolate. */
function runBuilderSnapTests(snap) {
  let checks = 0;
  const check = (condition, message) => { if (!condition) throw new Error(message); checks++; };
  const box = (left, top, width = 100, height = 100) => ({left, top, right: left + width, bottom: top + height});
  check(snap.grid(13, 4) === 12, 'Fine grid uses four-pixel blocks');
  check(snap.grid(-13, 4) === -12, 'Negative positions snap consistently');
  check(snap.grid(13, 4, -101) === 15, 'Document grid remains aligned after scrolling');
  check(snap.nearest([104], [100]).delta === -4, 'Edge within tolerance aligns');
  check(snap.nearest([108], [100]) === null, 'Distant edge does not attract');
  let match = snap.spacing(box(251, 0), [box(0, 0), box(124, 0)], 'x');
  check(match && match.delta === -3 && match.gap === 24, 'Third image inherits 24px horizontal gap');
  match = snap.spacing(box(-127, 0), [box(0, 0), box(124, 0)], 'x');
  check(match && match.delta === 3, 'Array can extend to the left');
  match = snap.spacing(box(127, 0), [box(0, 0), box(248, 0)], 'x');
  check(match && match.delta === -3 && match.gap === 24, 'Image between neighbours centres at equal gaps');
  match = snap.spacing(box(0, 251), [box(0, 0), box(0, 124)], 'y');
  check(match && match.delta === -3 && match.gap === 24, 'Vertical array gets matching spacing');
  check(snap.spacing(box(251, 300), [box(0, 0), box(124, 0)], 'x') === null, 'Different rows do not attract');
  check(snap.spacing(box(260, 0), [box(0, 0), box(124, 0)], 'x') === null, 'Outside tolerance movement remains free');
  check(snap.spacing(box(251, 0), [box(0, 0), box(124, 0), box(248, 0)], 'x') === null, 'Occupied image space is not a snap destination');
  match = snap.spacing(box(127, 0), [box(0, 0)], 'x', 6, 24);
  check(match && match.delta === -3 && match.gap === 24, 'Preferred gap works with just one neighbour');
  check(snap.spacing(box(130, 0), [box(0, 0)], 'x') === null, 'Single neighbour cannot invent a repeated gap');
  match = snap.spacing(box(352, 0, 140), [box(0, 0, 150), box(174, 0, 150)], 'x');
  check(match && match.delta === -4 && match.gap === 24, 'Unequal image widths keep equal edge gaps');
  return `${checks} builder geometry checks passed`;
}
if (typeof module !== 'undefined' && module.exports) console.log(runBuilderSnapTests(require('./static/builder-snap.js')));
