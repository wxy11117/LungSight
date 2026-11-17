import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

test('workspace distinguishes general knowledge, mixed sources, and the latest answer citations', () => {
  const page = readFileSync('app/agent/page.tsx', 'utf8');
  assert.ok(page.includes('医学通用问答 · 模型医学知识'));
  assert.ok(page.includes("GENERAL_KNOWLEDGE: '模型医学知识'"));
  assert.ok(page.includes("MIXED: '本地摘录 + 模型解读'"));
  assert.ok(page.includes("find((item) => item.role === 'assistant')?.citations"));
  assert.ok(!page.includes('无证据内容会被安全拦截'));
});

test('CT review uses the shared hybrid endpoint and distinguishes CT records from documents', () => {
  const page = readFileSync('app/review/page.tsx', 'utf8');
  assert.ok(page.includes('CT综合医学问答'));
  assert.ok(page.includes("card.source_type === 'ct-structured-result'"));
  assert.ok(page.includes('conversation_id: evidenceResults[0]?.conversation_id'));
  assert.ok(!page.includes('只基于已入库'));
});

test('CT analysis can request a grounded explanation without sending the image to the model provider', () => {
  const page = readFileSync('app/analysis/page.tsx', 'utf8');
  assert.ok(page.includes('/evidence/query'));
  assert.ok(page.includes('生成模型输出与局限说明'));
  assert.ok(page.includes('不得把类别排序称为病理诊断'));
  assert.ok(page.includes('不要给出分期或治疗建议'));
  assert.ok(page.includes('include_in_report: true'));
  assert.ok(page.includes('影像由本地服务处理'));
  assert.ok(page.includes("form.append('mode', uploadMode)"));
});
