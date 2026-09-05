import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { menuPosition, sortHistory } from '../app/agent/history-actions.ts';

const item = (id, last, pinned = null) => ({ conversation_id: id, title: id, last_message_at: last, pinned_at: pinned });

test('stars sort first, newest pins first, unpin restores recency without mutating history', () => {
  const items = [item('recent', '2026-08-30'), item('old', '2026-08-20', '2026-08-29'), item('star', '2026-08-21', '2026-08-30')];
  assert.deepEqual(sortHistory(items).map(x => x.conversation_id), ['star', 'old', 'recent']);
  assert.equal(items[0].conversation_id, 'recent');
  assert.deepEqual(sortHistory(items.map(x => ({ ...x, pinned_at: null }))).map(x => x.conversation_id), ['recent', 'star', 'old']);
  assert.deepEqual(sortHistory([]), []);
});

test('menu stays within desktop and small-screen viewport edges', () => {
  assert.deepEqual(menuPosition(30, 60, 210, 140, 1000, 800), { left: 30, top: 60 });
  assert.deepEqual(menuPosition(999, 799, 210, 140, 1000, 800), { left: 782, top: 652 });
  assert.deepEqual(menuPosition(320, 480, 210, 140, 320, 480), { left: 102, top: 332 });
  assert.deepEqual(menuPosition(-5, -5, 210, 140, 320, 480), { left: 8, top: 8 });
});

test('context menu contains four actions and uses selected record, not active chat', () => {
  const source = readFileSync(new URL('../app/agent/history-list.tsx', import.meta.url), 'utf8');
  assert.equal((source.match(/<button[^>]+role="menuitem"/g) || []).length, 4);
  for (const action of ['pin', 'share', 'copy']) assert.ok(source.includes(`act('${action}')`));
  assert.match(source, /encodeURIComponent\(selected\.conversation_id\)/);
  assert.match(source, /onContextMenu=/);
  assert.match(source, /ContextMenu/);
  assert.match(source, /F10/);
  assert.match(source, /showPopover\(\)/);
  assert.match(source, /showModal\(\)/);
  assert.match(source, /navigator\.clipboard\.writeText/);
  assert.match(source, /previewRef\.current\?\.select\(\)/);
  assert.doesNotMatch(source, /localStorage|dangerouslySetInnerHTML|window\.open/);
});

test('deletion needs confirmation and updates history only after a successful response', () => {
  const source = readFileSync(new URL('../app/agent/history-list.tsx', import.meta.url), 'utf8');
  const ask = source.split('const askDelete = () => {')[1].split('const confirmDelete')[0];
  assert.match(ask, /setPendingDelete\(selected\)/);
  assert.doesNotMatch(ask, /apiFetch|method: 'DELETE'/);
  assert.match(source, /method: 'DELETE'/);
  assert.match(source, /if \(!response.ok\) throw[\s\S]*onDeleted\(selectedId\)/);
  assert.match(source, /cancelDeleteRef.current\?\.focus\(\)/);
  assert.match(source, /目前没有界面恢复入口/);
  const page = readFileSync(new URL('../app/agent/page.tsx', import.meta.url), 'utf8');
  assert.match(page, /item.conversation_id !== id/);
  assert.match(page, /if \(activeId === id\) newConversation\(\)/);
});
