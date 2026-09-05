import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('return control targets the Agent directly without relying on history', () => {
  const component = source('../app/back-to-agent.tsx');
  assert.match(component, /<a\s[^>]*href="\/agent"/);
  assert.match(component, /aria-label="返回主页（Agent工作台）"/);
  assert.match(component, /<span>返回主页<\/span>/);
  assert.doesNotMatch(component, /history\.|router\.back|onClick=/);
});

test('every child workspace places the shared return control in its top header', () => {
  for (const route of ['analysis', 'review', 'library', 'evaluation']) {
    const page = source(`../app/${route}/page.tsx`);
    assert.match(page, /import BackToAgent from '\.\.\/back-to-agent'/, route);
    const header = page.match(/<header className="[^"\n]+">([\s\S]*?)<\/header>/)?.[1];
    assert.ok(header, route);
    assert.equal((header.match(/<BackToAgent \/>/g) || []).length, 1, route);
    // The narrow-screen rule keeps the first navigation link visible.
    assert.match(header, /<(?:nav|div)><BackToAgent \/>/, route);
    // Module switching belongs to the Agent homepage, not child-page headers.
    assert.doesNotMatch(header, /href="\/(?:analysis|review|library|evaluation)(?:[?"/])/, route);
  }
});

test('return control uses shared appearance and permits narrow header wrapping', () => {
  const css = source('../app/workspace-theme.css');
  const rule = css.match(/html\[data-theme\][^{]+a\.back-to-agent\s*\{([^}]+)\}/)?.[1];
  assert.ok(rule);
  assert.match(rule, /display: inline-flex/);
  assert.match(rule, /background: var\(--account-gradient\)/);
  assert.match(rule, /white-space: nowrap/);
  assert.match(css, /a\.back-to-agent:focus-visible/);
  assert.match(css, /@media \(max-width: 780px\)[\s\S]*flex-wrap: wrap/);
});
