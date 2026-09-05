import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { createScrollFollower, nearBottom } from '../app/agent/scroll-follow.ts';

test('short content and rounding count as the bottom, older long-chat content does not', () => {
  assert.ok(nearBottom({ scrollTop: 0, scrollHeight: 300, clientHeight: 600 }));
  assert.ok(nearBottom({ scrollTop: -1, scrollHeight: 600, clientHeight: 600 }));
  assert.ok(nearBottom({ scrollTop: 399.5, scrollHeight: 1000, clientHeight: 600 }));
  assert.equal(nearBottom({ scrollTop: 0, scrollHeight: 500000, clientHeight: 600 }), false);
});

test('following continues through answer growth until the reader scrolls upward', () => {
  const state = createScrollFollower();
  state.sync(400);
  state.observe({ scrollTop: 400, scrollHeight: 1100, clientHeight: 600 });
  assert.ok(state.following);
  state.observe({ scrollTop: 200, scrollHeight: 1100, clientHeight: 600 });
  assert.equal(state.following, false);
  for (let size = 1200; size <= 500000; size += 1000) {
    state.observe({ scrollTop: 200, scrollHeight: size, clientHeight: 600 });
    assert.equal(state.following, false);
  }
  state.observe({ scrollTop: 499400, scrollHeight: 500000, clientHeight: 600 });
  assert.ok(state.following);
});

test('even a small upward scroll pauses; jump-to-latest and new conversations reset intent', () => {
  const state = createScrollFollower();
  state.sync(400);
  state.observe({ scrollTop: 390, scrollHeight: 1000, clientHeight: 600 });
  assert.equal(state.following, false);
  state.reset();
  assert.ok(state.following);
  state.pause();
  assert.equal(state.following, false);
});

test('center is bounded and independently scrollable, with input outside the scroll pane', () => {
  const css = readFileSync(new URL('../app/agent/chat-scroll.css', import.meta.url), 'utf8');
  const page = readFileSync(new URL('../app/agent/page.tsx', import.meta.url), 'utf8');
  assert.match(css, /main\.rag-shell[^}]+height: 100dvh[^}]+overflow: hidden/);
  assert.match(css, /\.rag-workspace>\.chat-stage[^}]+display: flex[^}]+min-height: 0/);
  assert.match(css, /\.chat-stage>\.message-pane[^}]+flex: 1 1 0[^}]+min-height: 0/);
  assert.match(css, /\.message-pane>\.message-scroll[^}]+overflow-y: scroll[^}]+scrollbar-gutter: stable/);
  assert.match(css, /scrollbar-color: var\(--account-accent\) var\(--account-field\)/);
  assert.match(page, /className="message-scroll" role="region"[^>]+tabIndex=\{0\}/);
  assert.match(page, /chat-jump-latest[\s\S]*?<\/div>\s*<form className="chat-composer"/);
  assert.match(page, /const ChatMessage = memo/);
  assert.doesNotMatch(page, /messageEnd|scrollIntoView\(\{ behavior: 'smooth' \}\); \}, \[messages\]/);
});

test('stream scrolling is frame-coalesced and only targets the message container', () => {
  const hook = readFileSync(new URL('../app/agent/use-chat-scroll.ts', import.meta.url), 'utf8');
  assert.match(hook, /if \(frame.current !== null\) return/);
  assert.match(hook, /requestAnimationFrame/);
  assert.match(hook, /if \(follower.current.following\)/);
  assert.match(hook, /element.scrollTo/);
  assert.match(hook, /observer.disconnect\(\)/);
  assert.match(hook, /cancelAnimationFrame/);
  assert.doesNotMatch(hook, /window.scroll|scrollIntoView|behavior: 'smooth'/);
});
