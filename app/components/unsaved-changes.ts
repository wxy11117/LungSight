'use client';

import { useEffect, useRef } from 'react';

const editors = new Map<symbol, { dirty: boolean; busy: boolean }>();
let skipUnload = false;

export function confirmUnsavedChanges() {
  if ([...editors.values()].some(editor => editor.busy)) {
    window.alert('内容正在保存，请稍候再切换。');
    return false;
  }
  return ![...editors.values()].some(editor => editor.dirty) || window.confirm('有尚未保存的人工标记或复核内容。确定放弃这些输入并离开吗？');
}

function beforeUnload(event: BeforeUnloadEvent) {
  if (!skipUnload && [...editors.values()].some(editor => editor.dirty || editor.busy)) {
    event.preventDefault(); event.returnValue = '';
  }
}

function beforeLink(event: MouseEvent) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const link = (event.target as Element | null)?.closest<HTMLAnchorElement>('a[href]');
  if (!link || link.download || (link.target && link.target !== '_self')) return;
  const target = new URL(link.href, window.location.href);
  if (target.pathname === window.location.pathname && target.search === window.location.search) return;
  if (!confirmUnsavedChanges()) { event.preventDefault(); event.stopImmediatePropagation(); }
  else { skipUnload = true; window.setTimeout(() => { skipUnload = false; }, 1000); }
}

export function useUnsavedChanges(dirty: boolean, busy = false) {
  const id = useRef(Symbol('editor'));
  useEffect(() => {
    const key = id.current;
    editors.set(key, { dirty, busy });
    if (editors.size === 1) {
      window.addEventListener('beforeunload', beforeUnload);
      document.addEventListener('click', beforeLink, true);
    }
    return () => {
      editors.delete(key);
      if (!editors.size) {
        window.removeEventListener('beforeunload', beforeUnload);
        document.removeEventListener('click', beforeLink, true);
      }
    };
  }, [dirty, busy]);
}
