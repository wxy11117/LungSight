import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { formatClock } from '../app/agent/clock-format.ts';

test('clock shows 24-hour time with seconds and Chinese date/weekday', () => {
  const value = formatClock(new Date('2026-08-30T13:04:05Z'), 'Asia/Shanghai');
  assert.equal(value.time, '21:04:05');
  assert.equal(value.date, '2026年8月30日星期日');
});

test('midnight rolls date and weekday forward without showing 24:00', () => {
  const before = formatClock(new Date('2026-08-30T15:59:59Z'), 'Asia/Shanghai');
  const after = formatClock(new Date('2026-08-30T16:00:00Z'), 'Asia/Shanghai');
  assert.equal(before.time, '23:59:59');
  assert.equal(after.time, '00:00:00');
  assert.equal(after.date, '2026年8月31日星期一');
  assert.equal(formatClock(new Date('2028-02-28T16:00:00Z'), 'Asia/Shanghai').date, '2028年2月29日星期二');
});

test('device local time is used by default', () => {
  const value = new Date('2026-08-30T13:04:05Z');
  const zone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
  assert.deepEqual(formatClock(value), formatClock(value, zone));
});

test('clock replaces the greeting, isolates ticking state and cleans up timers', () => {
  const page = readFileSync('app/agent/page.tsx', 'utf8');
  const clock = readFileSync('app/agent/workspace-clock.tsx', 'utf8');
  assert.ok(page.includes('<WorkspaceClock />'));
  assert.ok(!page.includes('今天需要分析什么'));
  assert.ok(clock.includes('useState<Date | null>(null)'));
  assert.ok(clock.includes('setNow(new Date())'));
  assert.ok(clock.includes('window.setInterval(update, 1000)'));
  for (const cleanup of ['clearInterval(interval)', 'cancelAnimationFrame(frame)', "removeEventListener('visibilitychange', update)", "removeEventListener('focus', update)"]) assert.ok(clock.includes(cleanup));
  assert.ok(clock.includes('aria-live="off"'));
  const css = readFileSync('app/agent/workspace-clock.css', 'utf8');
  assert.ok(css.includes('tabular-nums'));
  assert.ok(css.includes('var(--account-text)'));
});
