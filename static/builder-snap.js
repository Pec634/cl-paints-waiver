/* Geometry shared by the preview and the snapping tests; coordinates are CSS pixels. */
(() => {
  function grid(value, step, origin = 0) { return origin + Math.round((value - origin) / step) * step; }
  function nearest(points, anchors, tolerance = 6) {
    let best = null;
    for (const point of points) for (const anchor of anchors) {
      const delta = anchor - point;
      if (Math.abs(delta) <= tolerance && (!best || Math.abs(delta) < Math.abs(best.delta))) best = {delta, anchor};
    }
    return best;
  }
  function spacing(rect, neighbours, axis, tolerance = 6, preferredGap = null) {
    const horizontal = axis === 'x', start = horizontal ? 'left' : 'top', end = horizontal ? 'right' : 'bottom';
    const crossStart = horizontal ? 'top' : 'left', crossEnd = horizontal ? 'bottom' : 'right';
    const length = rect[end] - rect[start];
    const sameBand = other => Math.min(rect[crossEnd], other[crossEnd]) - Math.max(rect[crossStart], other[crossStart]) >=
      Math.min(rect[crossEnd] - rect[crossStart], other[crossEnd] - other[crossStart]) * .5;
    const nearby = neighbours.filter(other => other[end] > other[start] && other[crossEnd] > other[crossStart] && sameBand(other)).sort((a, b) => a[start] - b[start]);
    let best = null;
    function candidate(position, gap, references) {
      const delta = position - rect[start];
      if (gap < 0 || gap > 240 || Math.abs(delta) > tolerance) return;
      const placed = {...rect, [start]: position, [end]: position + length};
      // Do not snap an image into another image's occupied area.
      if (nearby.some(other => Math.min(placed[end], other[end]) - Math.max(placed[start], other[start]) > .5)) return;
      if (!best || Math.abs(delta) < Math.abs(best.delta)) best = {delta, gap, axis, rect: placed, references};
    }
    const before = nearby.filter(other => other[end] <= rect[start] + tolerance).at(-1);
    const after = nearby.find(other => other[start] >= rect[end] - tolerance);
    if (before && after) {
      const gap = (after[start] - before[end] - length) / 2;
      candidate(before[end] + gap, gap, [before, after]);
    }
    for (let index = 0; index < nearby.length - 1; index++) {
      const first = nearby[index], second = nearby[index + 1], gap = second[start] - first[end];
      if (gap < 0 || gap > 240) continue;
      candidate(first[start] - gap - length, gap, [first, second]);
      candidate(second[end] + gap, gap, [first, second]);
    }
    if (Number.isFinite(preferredGap) && preferredGap >= 0 && preferredGap <= 240) {
      nearby.forEach(other => {
        candidate(other[start] - preferredGap - length, preferredGap, [other]);
        candidate(other[end] + preferredGap, preferredGap, [other]);
      });
    }
    return best;
  }
  const geometry = {grid, nearest, spacing};
  globalThis.BuilderSnap = geometry;
  if (typeof module !== 'undefined' && module.exports) module.exports = geometry;
})();
