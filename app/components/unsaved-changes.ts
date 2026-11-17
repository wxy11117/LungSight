'use client';

import { useEffect, useRef } from 'react';
import { confirmAction } from './confirmation-dialog';

const editors = new Map<symbol, { dirty: boolean; busy: boolean }>();
let skipUnload = false;

export async function confirmUnsavedChanges() {
  if ([...editors.values()].some(editor => editor.busy)) {
    await confirmAction({ title: '正在保存内容', description: '请等待当前保存完成，再切换页面。', confirmLabel: '知道了', cancelLabel: '留在当前页' });
    return false;
  }
  return ![...editors.values()].some(editor => editor.dirty) || await confirmAction({ title: '保留尚未保存的内容？', description: '当前修改还未保存。你可以返回继续编辑，或放弃本次输入后离开。', confirmLabel: '放弃并继续', cancelLabel: '继续编辑', destructive: true });
}

function beforeUnload(event: BeforeUnloadEvent) {
  if (!skipUnload && [...editors.values()].some(editor => editor.dirty || editor.busy)) {
    event.preventDefault(); event.returnValue = '';
  }
}

async function beforeLink(event: MouseEvent) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const link = (event.target as Element | null)?.closest<HTMLAnchorElement>('a[href]');
  if (!link || link.download || (link.target && link.target !== '_self')) return;
  const target = new URL(link.href, window.location.href);
  if (target.pathname === window.location.pathname && target.search === window.location.search) return;
  if (![...editors.values()].some(editor => editor.dirty || editor.busy)) return;
  event.preventDefault(); event.stopImmediatePropagation();
  if (await confirmUnsavedChanges()) {
    skipUnload = true;
    window.location.assign(target.href);
    window.setTimeout(() => { skipUnload = false; }, 1000);
  }
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
