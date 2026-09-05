import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync(new URL('../app/review/page.tsx', import.meta.url), 'utf8');

test('historical review media is cache-busted after task or path updates', () => {
  assert.match(page, /\/api\/tasks\/\$\{detail\.task_id\}\/\$\{imageMode === 'attention'/);
  assert.match(page, /\?v=\$\{encodeURIComponent\(detail\.updated_at\)\}/);
});
