import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { Script, createContext, runInContext } from 'node:vm';

// 使用实际单文件脚本验证交互和认证请求，不操作用户账号或登录会话。
const html = readFileSync(new URL('../public/auth-panel/index.html', import.meta.url), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
new Script(script);

function harness() {
  let document;
  class Element {
    listeners = new Map(); attributes = {}; value = ''; hidden = false; disabled = false; textContent = '';
    style = { transform: '', setProperty(name, value) { this[name] = value; } };
    addEventListener(name, handler) { this.listeners.set(name, [...(this.listeners.get(name) || []), handler]); }
    async fire(name, event = {}) { for (const handler of this.listeners.get(name) || []) await handler(event); }
    setAttribute(name, value) { this.attributes[name] = value; }
    getBoundingClientRect() { return { left: 80, top: 120, width: 380, height: 720 }; }
    reportValidity() { return true; }
    focus() { document.activeElement?.fire('blur'); document.activeElement = this; this.fire('focus'); }
  }
  const elements = Object.fromEntries(['companions', 'scene-caption', 'phone', 'email', 'password', 'password-toggle', 'notice', 'login-form', 'login-fields', 'register', 'submit-label', 'calling-code', 'phone-field', 'email-field'].map((id) => [id, new Element()]));
  elements['calling-code'].value = '+86'; elements.password.type = 'password';
  const buttons = ['phone', 'email'].map((method) => Object.assign(new Element(), { dataset: { method } }));
  const eyes = Array.from({ length: 6 }, () => { const eye = new Element(); const pupil = new Element(); eye.querySelector = () => pupil; return eye; });
  const root = new Element(); root.dataset = {};
  document = Object.assign(new Element(), {
    documentElement: root, getElementById: (id) => elements[id],
    querySelectorAll: (selector) => selector === '.eye' ? eyes : buttons,
    querySelector: () => new Element(),
  });
  const messages = []; const requests = []; const frames = new Map(); let frameId = 0;
  const parent = { postMessage: (value, origin) => messages.push({ value, origin }) };
  const window = Object.assign(new Element(), {
    parent, location: { origin: 'http://127.0.0.1:3000', protocol: 'http:', replace() {}, assign() {} },
    matchMedia: () => Object.assign(new Element(), { matches: false }),
  });
  const context = createContext({ document, window, location: window.location, URL, AbortController, console,
    ResizeObserver: class { observe() {} },
    requestAnimationFrame: (callback) => { frames.set(++frameId, callback); return frameId; },
    cancelAnimationFrame: (id) => frames.delete(id), setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options) => { requests.push({ url, options }); return { ok: true, json: async () => ({ user: { user_id: 'test-only' } }) }; },
  });
  runInContext(script, context);
  const evalCode = (code) => runInContext(code, context);
  const configure = () => window.fire('message', { source: parent, origin: window.location.origin, data: { type: 'lungsight:login-config', apiBaseUrl: 'http://127.0.0.1:8001', theme: 'eye', tokens: {} } });
  return { context, elements, buttons, eyes, root, window, parent, messages, requests, frames, evalCode, configure };
}

test('账号焦点探头；密码明文优先遮眼，移动鼠标不再跟随，隐藏后恢复', async () => {
  const h = harness();
  h.elements.phone.focus(); assert.match(h.elements.companions.className, /peeking/);
  h.evalCode('trackPointer(800, 500)'); assert.equal(h.frames.size, 1);
  await h.elements['password-toggle'].fire('click');
  assert.equal(h.elements.password.type, 'text'); assert.match(h.elements.companions.className, /covering/);
  assert.equal(h.frames.size, 0); assert.equal(h.elements['password-toggle'].attributes['aria-label'], '隐藏密码');
  h.evalCode('trackPointer(-100, 500)'); assert.equal(h.frames.size, 0);
  await h.elements.phone.fire('blur'); assert.match(h.elements.companions.className, /covering/);
  await h.elements['password-toggle'].fire('click');
  assert.equal(h.elements.password.type, 'password'); assert.match(h.elements.companions.className, /normal/);
  h.evalCode('trackPointer(-100, 500)'); assert.equal(h.frames.size, 1);
});

test('瞳孔方向正确且始终位于眼白范围内', () => {
  const h = harness();
  for (const [dx, dy] of [[0, 0], [1e6, 0], [-1e6, 50], [40, -700]]) {
    const offset = h.context.gazeOffset(dx, dy);
    assert.ok(Math.hypot(offset.x, offset.y) <= 4.00001);
    if (dx) assert.equal(Math.sign(offset.x), Math.sign(dx));
    if (dy) assert.equal(Math.sign(offset.y), Math.sign(dy));
  }
});

test('切换邮箱会清空并隐藏密码，登录沿用现有接口和Cookie且消息不传密码', async () => {
  const h = harness(); await h.configure();
  h.elements.password.value = 'old-secret'; h.evalCode('setPasswordVisibility(true)');
  await h.buttons[1].fire('click');
  assert.equal(h.elements.phone.disabled, true); assert.equal(h.elements.email.required, true);
  assert.equal(h.elements.password.value, ''); assert.equal(h.elements.password.type, 'password');
  h.elements.email.value = '  DOCTOR@EXAMPLE.COM '; h.elements.password.value = 'test-secret';
  await h.elements['login-form'].fire('submit', { preventDefault() {} });
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, 'http://127.0.0.1:8001/api/auth/login');
  assert.equal(h.requests[0].options.credentials, 'include');
  assert.deepEqual(JSON.parse(h.requests[0].options.body), { email: 'doctor@example.com', password: 'test-secret' });
  assert.equal(h.elements.password.value, '');
  assert.ok(h.messages.some(({ value }) => value.type === 'lungsight:login-success'));
  assert.doesNotMatch(JSON.stringify(h.messages), /test-secret|doctor@example/);
});

test('手机号规范化与错误反馈可恢复；失败不发送成功消息', async () => {
  const h = harness(); await h.configure();
  h.elements.phone.value = '138 0013-8000'; h.elements.password.value = 'wrong-pass';
  h.context.fetch = async (url, options) => {
    assert.deepEqual(JSON.parse(options.body), { phone: '+8613800138000', password: 'wrong-pass' });
    return { ok: false, status: 401, json: async () => ({ detail: '账号或密码不正确' }) };
  };
  await h.elements['login-form'].fire('submit', { preventDefault() {} });
  assert.equal(h.elements.notice.textContent, '账号或密码不正确');
  assert.equal(h.elements['login-fields'].disabled, false);
  assert.equal(h.elements['login-form'].attributes['aria-busy'], 'false');
  assert.equal(h.messages.some(({ value }) => value.type === 'lungsight:login-success'), false);
});

test('拒绝其他来源和其他窗口的服务配置，允许同源主题同步', async () => {
  const h = harness();
  for (const [source, origin] of [[h.parent, 'https://untrusted.example'], [{}, h.window.location.origin]]) {
    await h.window.fire('message', { source, origin, data: { type: 'lungsight:login-config', apiBaseUrl: 'https://untrusted.example', theme: 'dark' } });
    assert.equal(h.evalCode('configured'), false);
    assert.equal(h.evalCode('apiBase'), 'http://127.0.0.1:8001');
  }
  await h.configure(); assert.equal(h.evalCode('configured'), true); assert.equal(h.root.dataset.theme, 'eye');
});

test('注册入口清空密码并回到父页面既有注册流程', async () => {
  const h = harness(); h.elements.password.value = 'secret'; h.evalCode('setPasswordVisibility(true)');
  await h.elements.register.fire('click');
  assert.equal(h.elements.password.value, ''); assert.equal(h.elements.password.type, 'password');
  assert.ok(h.messages.some(({ value }) => value.type === 'lungsight:register'));
});
