import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

test('welcome orb shares the live account avatar and profile update state', () => {
  const page = readFileSync('app/agent/page.tsx', 'utf8');
  assert.ok(page.includes('className="agent-orb" role="img" aria-label="当前账号头像"><span><UserAvatar user={user} />'));
  assert.ok(page.includes('onUserUpdated={setUser}'));
  assert.ok(!page.includes('className="agent-orb"><span>LS</span>'));
  assert.ok(!page.includes('<Image src="/qions-med-icon.png"'));
  const menu = readFileSync('app/agent/account-menu.tsx', 'utf8');
  assert.match(menu, /onSaved=\{\(updated\) => \{ onUserUpdated\(updated\)/);
  assert.ok(page.includes('<WorkspaceClock />'));
  assert.ok(page.includes('<UserAvatar user={user} />'));
});

test('welcome avatar fits its existing circular frame with a readable initial fallback', () => {
  const css = readFileSync('app/agent/agent-emblem.css', 'utf8');
  assert.ok(css.includes('object-fit: cover'));
  assert.ok(css.includes('border-radius: 50%'));
  assert.ok(css.includes('font-size: 26px'));
  const avatar = readFileSync('app/agent/profile-editor.tsx', 'utf8');
  assert.ok(avatar.includes('const avatarUrl = user?.avatar_url'));
  assert.ok(avatar.includes('failedUrl !== avatarUrl'));
  assert.ok(avatar.includes("user?.display_name.trim() || 'U'"));
});
