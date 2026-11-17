import assert from 'node:assert/strict';
import test from 'node:test';
import { fitImage, imagePoint, boundedPan } from '../app/components/viewer-geometry.ts';

test('rectangular images retain aspect ratio in wide and narrow viewports', () => {
  assert.deepEqual(fitImage(1024, 512, 800, 440), { width: 800, height: 400 });
  assert.deepEqual(fitImage(512, 1024, 320, 440), { width: 220, height: 440 });
});

test('annotation coordinates are unchanged after scaling and panning the plane', () => {
  const before = imagePoint(300, 150, { left: 100, top: 50, width: 800, height: 400 });
  const after = imagePoint(300, 200, { left: -100, top: 0, width: 1600, height: 800 });
  assert.deepEqual(before, { x: .25, y: .25 });
  assert.deepEqual(after, before);
  assert.equal(imagePoint(99, 50, { left: 100, top: 50, width: 800, height: 400 }), null);
  assert.equal(imagePoint(10, 10, { left: 0, top: 0, width: 0, height: 0 }), null);
});

test('panning cannot lose the image and returning to fit resets its translation', () => {
  assert.deepEqual(boundedPan(9999, -9999, 800, 400, 2), { x: 400, y: -200 });
  assert.equal(Math.abs(boundedPan(100, -100, 800, 400, 1).x), 0);
  assert.equal(Math.abs(boundedPan(100, -100, 800, 400, 1).y), 0);
});
