import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { accents, themes, appearanceBootstrap, appearanceKey, defaultAppearance, parseAppearance, applyAppearance, readAppearance, saveAppearance } from '../app/appearance.ts';

test('existing Agent appearance key is retained', () => {
  assert.equal(appearanceKey, 'lungsight.workspace-appearance.v1');
  const current = { theme: 'light', accent: 'rainbow' };
  assert.deepEqual(readAppearance({ getItem: (key) => key === appearanceKey ? JSON.stringify(current) : null }), current);
});

test('all twelve combinations survive reload on every workspace route', () => {
  for (const theme of themes) for (const accent of accents) {
    const value = { theme: theme.id, accent: accent.id };
    let saved;
    assert.equal(saveAppearance({ setItem: (key, raw) => { assert.equal(key, appearanceKey); saved = raw; } }, value), true);
    assert.deepEqual(parseAppearance(saved), value);
    for (const route of ['/agent', '/analysis', '/review', '/library', '/evaluation', '/settings', '/cases', '/case']) {
      const root = { dataset: {} };
      runInNewContext(appearanceBootstrap, { localStorage: { getItem: () => saved }, document: { documentElement: root }, location: { pathname: route } });
      assert.deepEqual(root.dataset, value, route);
    }
  }
});

test('runtime and first-paint parsers both reject malformed and unsupported values', () => {
  for (const raw of [null, '', '{', 'null', '[]', '3', '{}', '{"theme":"light"}', '{"theme":"system","accent":"classic"}', '{"theme":"light","accent":"unknown"}', '{"theme":"light;alert(1)","accent":"classic"}']) {
    assert.deepEqual(parseAppearance(raw), defaultAppearance);
    const root = { dataset: {} };
    runInNewContext(appearanceBootstrap, { localStorage: { getItem: () => raw }, document: { documentElement: root } });
    assert.deepEqual(root.dataset, defaultAppearance);
  }
});

test('blocked storage does not break startup or in-memory appearance changes', () => {
  const denied = { getItem: () => { throw Error('disabled'); }, setItem: () => { throw Error('disabled'); } };
  assert.deepEqual(readAppearance(denied), defaultAppearance);
  const root = { dataset: {} };
  runInNewContext(appearanceBootstrap, { localStorage: denied, document: { documentElement: root } });
  assert.deepEqual(root.dataset, defaultAppearance);
  const current = { theme: 'eye', accent: 'sunset' };
  assert.equal(saveAppearance(denied, current), false);
  applyAppearance(root, current);
  assert.deepEqual(root.dataset, current);
});

test('theme change and cross-tab removal replace both root attributes', () => {
  const root = { dataset: { theme: 'dark', accent: 'classic', unrelated: 'keep' } };
  applyAppearance(root, parseAppearance('{"theme":"eye","accent":"aurora"}'));
  assert.deepEqual(root.dataset, { theme: 'eye', accent: 'aurora', unrelated: 'keep' });
  applyAppearance(root, parseAppearance(null));
  assert.deepEqual(root.dataset, { ...defaultAppearance, unrelated: 'keep' });
});

test('only appearance fields are read from a saved object', () => {
  assert.deepEqual(parseAppearance('{"theme":"light","accent":"classic","email":"ignored@example.com"}'), { theme: 'light', accent: 'classic' });
});

test('root owns theme state and initialization precedes body content', () => {
  const layout = readFileSync(new URL('../app/layout.tsx', import.meta.url), 'utf8');
  const agent = readFileSync(new URL('../app/agent/page.tsx', import.meta.url), 'utf8');
  const provider = readFileSync(new URL('../app/appearance-provider.tsx', import.meta.url), 'utf8');
  assert.match(layout, /<AppearanceProvider>\{children\}<\/AppearanceProvider>/);
  assert.match(layout, /import '\.\/workspace-theme\.css'/);
  assert.ok(layout.indexOf('__html: appearanceBootstrap') < layout.indexOf('<body'));
  assert.doesNotMatch(agent, /data-theme=|data-accent=/);
  assert.match(provider, /addEventListener\('storage'/);
  assert.match(provider, /removeEventListener\('storage'/);
});

test('all child workspaces receive palette rules without filtering clinical images', () => {
  const css = readFileSync(new URL('../app/workspace-theme.css', import.meta.url), 'utf8');
  const accountCss = readFileSync(new URL('../app/agent/account-menu.css', import.meta.url), 'utf8');
  for (const name of ['analysis', 'review', 'library', 'evaluation']) assert.ok(css.includes(`.${name}-shell`));
  for (const name of ['analysis-run', 'submit-review', 'evaluation-hero button', 'rag-eval-title button']) assert.ok(css.includes(`.${name}`));
  assert.doesNotMatch(css, /\.(?:analysis-image|review-image)\s+img/);
  assert.doesNotMatch(css, /(?:filter|mix-blend-mode)\s*:/);
  assert.doesNotMatch(accountCss, /\.rag-shell\[data-|\.rag-shell:is\(\[data-theme/);
});

test('Agent search, quick model switch and provider status share the three-mode palette', () => {
  const css = readFileSync(new URL('../app/agent/account-menu.css', import.meta.url), 'utf8');
  for (const selector of ['.workspace-search', '.model-quick-switch summary', '.context-actions>button', '.provider-status-card']) {
    assert.ok(css.includes(selector), selector);
  }
  assert.match(css, /\.rag-shell\s+:is\([\s\S]*\.workspace-search[\s\S]*\.provider-status-card[\s\S]*background:\s*var\(--account-surface\)/);
  assert.match(css, /\.rag-shell \.model-quick-switch summary \{ color: var\(--account-accent\); \}/);
  assert.match(css, /\.rag-shell \.provider-status-card>strong \{ color: var\(--account-text\); \}/);
  assert.match(css, /\.rag-shell \.provider-status-card>p \{ color: var\(--account-muted\); \}/);
  assert.match(css, /\.top-action-nav>a\s*\{[\s\S]*background: var\(--account-surface\)/);
  assert.match(css, /\.top-action-nav>a:hover\s*\{[\s\S]*background: var\(--workspace-soft\)/);
});

test('shared LungSight brand mark uses the transparent emblem without a dark backing tile', () => {
  const css = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');
  assert.match(css, /\.brand-mark\s*\{[^}]*background:\s*transparent[^}]*lungsight-brand-transparent\.png/s);
  assert.doesNotMatch(css, /\.brand-mark\s*\{[^}]*linear-gradient\(145deg,#0c2b31,#061218/s);
});
