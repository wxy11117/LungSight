import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('case library exposes an accessible context menu for star archive and delete', () => {
  const table = source('../app/cases/case-table.tsx');
  const page = source('../app/cases/page.tsx');
  assert.match(table, /onContextMenu=/);
  assert.match(table, /Shift\+F10/);
  assert.match(table, /加星标/);
  assert.match(table, /归档病例/);
  assert.match(table, /删除病例/);
  assert.match(table, /PERMANENT DELETE/);
  assert.match(table, /method: 'PATCH'/);
  assert.match(table, /method: 'DELETE'/);
  assert.match(page, /CaseTable/);
});

test('settings center includes archived cases with restore and permanent deletion', () => {
  const settings = source('../app/settings/page.tsx');
  assert.match(settings, /查看归档/);
  assert.match(settings, /\/api\/tasks\?archived=true/);
  assert.match(settings, /<CaseTable archived/);
  assert.match(settings, /恢复或永久删除病例/);
});

test('starred cases sort before recency without mutating source data', async () => {
  const module = await import('../app/cases/case-actions.ts');
  const base = { status: '', file_name: '', top_class_cn: '', top_probability: 0, reliability_level: '', fold_agreement: '', quality_status: '', priority: '', attention_available: false, reviewer_name: null, corrected_class_cn: null, archived_at: null };
  const input = [
    { ...base, task_id: 'new', created_at: '2026-09-04', starred_at: null },
    { ...base, task_id: 'old-star', created_at: '2026-09-01', starred_at: '2026-09-04T10:00:00Z' },
  ];
  assert.deepEqual(module.sortCases(input).map((item) => item.task_id), ['old-star', 'new']);
  assert.deepEqual(input.map((item) => item.task_id), ['new', 'old-star']);
});

