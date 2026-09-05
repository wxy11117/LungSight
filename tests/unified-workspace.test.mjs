import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('Agent keeps the central medical chat and moves secret configuration to settings', () => {
  const agent = source('../app/agent/page.tsx');
  assert.match(agent, /className="chat-stage"/);
  assert.match(agent, /WorkspaceClock/);
  assert.match(agent, /模型服务设置/);
  assert.match(agent, /\/api\/settings\/llm\/select/);
  assert.doesNotMatch(agent, /type="password"/);
  assert.doesNotMatch(agent, /保存并启用/);
});

test('top bar exposes global search, notification and configured-model quick switch', () => {
  const agent = source('../app/agent/page.tsx');
  assert.match(agent, /workspace-search/);
  assert.match(agent, /搜索病例或历史问答/);
  assert.match(agent, /model-quick-switch/);
  assert.match(agent, /className="top-action-nav"/);
  for (const path of ['/library', '/evaluation', '/review']) assert.match(agent, new RegExp(`<a href="${path.replace('/', '\\/')}"`));
  assert.doesNotMatch(agent, /<Link href="\/(?:library|evaluation|review)"/);
});

test('complete API configuration lives in Settings Center', () => {
  const settings = source('../app/settings/page.tsx');
  assert.match(settings, /本账号累计Token用量/);
  assert.match(settings, /type="password"/);
  assert.match(settings, /测试连接/);
  assert.match(settings, /删除配置/);
  assert.match(settings, /\/api\/settings\/llm/);
});

test('critical workspace navigation uses reliable document links', () => {
  const agent = source('../app/agent/page.tsx');
  assert.match(agent, /<a href="\/settings">打开模型服务设置 →<\/a>/);
  assert.match(agent, /<a href="\/settings">模型服务设置 →<\/a>/);
  for (const page of ['agent', 'analysis', 'review', 'library', 'evaluation', 'settings', 'cases', 'case']) {
    const file = source(`../app/${page}/page.tsx`);
    assert.doesNotMatch(file, /from 'next\/link'/, page);
    assert.doesNotMatch(file, /<Link\b/, page);
  }
});

test('case library and unified case workspace preserve the full task flow', () => {
  const library = source('../app/cases/page.tsx');
  const caseTable = source('../app/cases/case-table.tsx');
  const workspace = source('../app/case/page.tsx');
  assert.match(library, /搜索病例编号、文件名或分类/);
  assert.match(caseTable, /\/case\?task=/);
  assert.match(workspace, /影像与分析/);
  assert.match(workspace, /AI解释与证据/);
  assert.match(workspace, /医生复核/);
  assert.match(workspace, /审计记录/);
  assert.match(workspace, /apiBaseUrl}\/api\/tasks/);
  assert.match(workspace, /'attention' : 'image'/);
});

test('long-running answers can stop and drafts are restored locally', () => {
  const agent = source('../app/agent/page.tsx');
  assert.match(agent, /AbortController/);
  assert.match(agent, /停止生成/);
  assert.match(agent, /lungsight-agent-draft/);
  assert.match(agent, /再次提问/);
});

test('account menu presents the requested local test-version notice', () => {
  const menu = source('../app/agent/account-menu.tsx');
  assert.match(menu, /当前为测试版本，账号、问答记录和CT任务保存在本机后端/);
  assert.match(menu, /识别所需的API Key需要用户自行配置/);
  assert.match(menu, /LungSight v\{version\} · 公共测试版本。/);
  assert.doesNotMatch(menu, /暂未接入在线版本查询和自动更新服务/);
});

test('account menu includes contact email and QIONX signature', () => {
  const menu = source('../app/agent/account-menu.tsx');
  assert.match(menu, /联系我们/);
  assert.match(menu, /mailto:2934935729@qq\.com/);
  assert.match(menu, /QIONX Exploration Technologies/);
  assert.match(menu, /qionx-main/);
  assert.match(menu, /qionx-x/);
  assert.match(menu, /EXPLORATION TECHNOLOGIES/);
});

test('logging out requires an explicit confirmation before revoking the session', () => {
  const menu = source('../app/agent/account-menu.tsx');
  const css = source('../app/agent/account-menu.css');
  assert.match(menu, /确认退出登录？/);
  assert.match(menu, /setConfirmingLogout\(true\)/);
  assert.match(menu, /confirmingLogout && <LogoutConfirm/);
  assert.match(menu, /onConfirm=\{\(\) => void signOut\(\)\}/);
  assert.match(menu, /确认退出/);
  assert.match(css, /\.logout-confirm::backdrop/);
  assert.match(css, /html:is\(\[data-theme="light"\], \[data-theme="eye"\]\) \.logout-confirm/);
});

test('account switching lists local accounts and reauthenticates before replacing the session', () => {
  const menu = source('../app/agent/account-menu.tsx');
  const css = source('../app/agent/account-menu.css');
  assert.match(menu, /apiFetch\('\/api\/auth\/accounts'/);
  assert.match(menu, /apiFetch\('\/api\/auth\/switch'/);
  assert.match(menu, /验证成功前，当前账号不会退出/);
  assert.match(menu, /type="password" autoComplete="current-password"/);
  assert.match(menu, /验证并切换/);
  assert.doesNotMatch(menu, /sessionStorage|localStorage/);
  assert.match(css, /\.account-switcher::backdrop/);
  assert.match(css, /\.account-switch-list>button\.selected/);
});
