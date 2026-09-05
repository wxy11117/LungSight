import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const page = readFileSync('app/library/page.tsx', 'utf8');
test('library distinguishes morphology, CT, normal class, original sources and training', () => {
  for (const text of ['细胞与病理形态', 'CT影像征象', 'CT分型预测研究', '四分类 ≠ 四种癌细胞', '不会重新训练影像模型', '查看整理内容', '访问原站', '本机共享']) assert.ok(page.includes(text));
  assert.ok(page.includes('<BackToAgent />'));
});
test('online import has an explicit original-note review gate and no chat upload', () => {
  assert.ok(page.includes('JSON.stringify({ pmid, topic: online.topic })'));
  assert.ok(page.includes('JSON.stringify({ enabled, note, acknowledged })'));
  assert.ok(page.includes('note.trim().length < 20'));
  assert.ok(page.includes('不发送CT、账号信息或对话内容'));
  assert.ok(page.includes('导入为待核对'));
  assert.ok(page.includes('停用检索'));
  assert.ok(page.includes('role="alert"'));
});
test('research styles reuse cross-page theme tokens and responsive form layout', () => {
  const css = readFileSync('app/library/library-research.css', 'utf8');
  assert.ok(css.includes('var(--account-surface)'));
  assert.ok(css.includes('var(--account-text)'));
  assert.ok(css.includes('focus-visible'));
  assert.ok(css.includes('@media(max-width:780px)'));
});

test('user-facing workspace copy has no legacy competition branding', () => {
  for (const route of ['agent', 'auth', 'analysis', 'review', 'library', 'evaluation']) {
    const content = readFileSync('app/' + route + '/page.tsx', 'utf8');
    assert.doesNotMatch(content, /竞赛|apmcm/iu, route);
  }
  assert.doesNotMatch(readFileSync('app/page.tsx', 'utf8'), /竞赛|apmcm/iu);
});
