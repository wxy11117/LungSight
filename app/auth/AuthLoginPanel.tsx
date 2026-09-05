'use client';

import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { apiBaseUrl, apiFetch } from '../auth-client';

const themeTokens = ['--account-surface', '--account-field', '--account-text', '--account-muted', '--account-border', '--account-accent', '--account-gradient', '--workspace-backdrop'];

/** 纯 HTML 登录面板的接入层；只同步外观、鼠标位置与导航，不传递密码。 */
export default function AuthLoginPanel({ onRegister, returnTo }: { onRegister: () => void; returnTo: RefObject<string> }) {
  const frame = useRef<HTMLIFrameElement>(null);

  const syncTheme = () => {
    const computed = getComputedStyle(document.documentElement);
    frame.current?.contentWindow?.postMessage({
      type: 'lungsight:login-config', apiBaseUrl,
      theme: document.documentElement.dataset.theme || 'light',
      tokens: Object.fromEntries(themeTokens.map((token) => [token, computed.getPropertyValue(token).trim()])),
    }, window.location.origin);
  };

  useEffect(() => {
    let disposed = false;
    let pointerFrame = 0;
    const receive = (event: MessageEvent) => {
      // 仅接收本站登录 iframe 的消息，其他页面不能触发导航。
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow || !event.data) return;
      if (event.data.type === 'lungsight:login-ready') syncTheme();
      if (event.data.type === 'lungsight:login-resize' && Number.isFinite(event.data.height)) {
        if (frame.current) frame.current.style.height = `${Math.max(300, Math.min(2400, Math.ceil(event.data.height)))}px`;
      }
      if (event.data.type === 'lungsight:register') onRegister();
      if (event.data.type === 'lungsight:login-success') {
        // 导航前重新向后端确认会话，消息本身不代表认证通过。
        void apiFetch('/api/auth/me', { cache: 'no-store' }).then((response) => {
          if (disposed) return;
          if (response.ok) window.location.replace(returnTo.current);
          else frame.current?.contentWindow?.postMessage({ type: 'lungsight:login-session-error' }, window.location.origin);
        }).catch(() => {
          if (!disposed) frame.current?.contentWindow?.postMessage({ type: 'lungsight:login-session-error' }, window.location.origin);
        });
      }
    };
    // 鼠标在左侧说明区时也能看向它；每帧最多发送一次，不触发 React 重渲染。
    const follow = (event: MouseEvent) => {
      cancelAnimationFrame(pointerFrame);
      pointerFrame = requestAnimationFrame(() => {
        const rect = frame.current?.getBoundingClientRect();
        if (rect) frame.current?.contentWindow?.postMessage({ type: 'lungsight:login-pointer', x: event.clientX - rect.left, y: event.clientY - rect.top }, window.location.origin);
      });
    };
    const reset = () => frame.current?.contentWindow?.postMessage({ type: 'lungsight:login-pointer-reset' }, window.location.origin);
    const observer = new MutationObserver(syncTheme);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-accent', 'style'] });
    window.addEventListener('message', receive);
    document.addEventListener('mousemove', follow, { passive: true });
    document.documentElement.addEventListener('mouseleave', reset);
    window.addEventListener('blur', reset);
    return () => {
      disposed = true;
      observer.disconnect();
      cancelAnimationFrame(pointerFrame);
      window.removeEventListener('message', receive);
      document.removeEventListener('mousemove', follow);
      document.documentElement.removeEventListener('mouseleave', reset);
      window.removeEventListener('blur', reset);
    };
  }, [onRegister, returnTo]);

  return <iframe ref={frame} onLoad={syncTheme} className="auth-companions-frame" src="/auth-panel/index.html?embedded=1" title="LungSight 互动登录：手机号或邮箱登录" />;
}
