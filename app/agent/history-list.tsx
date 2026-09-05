'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { apiFetch, responseMessage } from '../auth-client';
import { menuPosition, sortHistory } from './history-actions';
import type { HistoryConversation } from './history-actions';
import './history-list.css';

type ExportText = { title: string; text: string; filename: string };
type MenuTarget = { item: HistoryConversation; x: number; y: number };
type Props = {
  items: HistoryConversation[];
  activeId: string | null;
  busy: boolean;
  onSelect: (id: string) => Promise<void>;
  onPinUpdated: (id: string, pinnedAt: string | null) => void;
  onDeleted: (id: string) => void;
};
const date = (value: string) => new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));

export default function HistoryList({ items, activeId, busy, onSelect, onPinUpdated, onDeleted }: Props) {
  const menuRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const deleteDialogRef = useRef<HTMLDialogElement>(null);
  const cancelDeleteRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLTextAreaElement>(null);
  const returnFocus = useRef<HTMLButtonElement | null>(null);
  const operation = useRef(false);
  const [menu, setMenu] = useState<MenuTarget | null>(null);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [share, setShare] = useState<ExportText | null>(null);
  const [dialogNotice, setDialogNotice] = useState('');
  const [pendingDelete, setPendingDelete] = useState<HistoryConversation | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const menuId = useId();
  const dialogTitleId = useId();
  const deleteTitleId = useId();
  const deleteDescriptionId = useId();

  const closeMenu = useCallback((restoreFocus = false) => {
    menuRef.current?.hidePopover();
    setMenu(null);
    if (restoreFocus) returnFocus.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    if (!menu) return;
    const element = menuRef.current;
    if (!element) return;
    element.showPopover();
    const rect = element.getBoundingClientRect();
    const position = menuPosition(menu.x, menu.y, rect.width, rect.height, window.innerWidth, window.innerHeight);
    element.style.left = `${position.left}px`;
    element.style.top = `${position.top}px`;
    element.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus({ preventScroll: true });
    const close = () => closeMenu();
    const onScroll = (event: Event) => { if (!(event.target instanceof Node) || !element.contains(event.target)) close(); };
    window.addEventListener('resize', close);
    window.addEventListener('scroll', onScroll, true);
    return () => { window.removeEventListener('resize', close); window.removeEventListener('scroll', onScroll, true); };
  }, [menu, closeMenu]);

  useEffect(() => {
    if (!share) return;
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => { dialog?.close(); returnFocus.current?.focus({ preventScroll: true }); };
  }, [share]);

  useEffect(() => {
    if (!pendingDelete) return;
    const dialog = deleteDialogRef.current;
    const historySummary = listRef.current?.closest('details')?.querySelector('summary');
    dialog?.showModal();
    cancelDeleteRef.current?.focus();
    return () => {
      dialog?.close();
      if (returnFocus.current?.isConnected) returnFocus.current.focus({ preventScroll: true });
      else historySummary?.focus({ preventScroll: true });
    };
  }, [pendingDelete]);

  const openMenu = (event: MouseEvent<HTMLButtonElement> | KeyboardEvent<HTMLButtonElement>, item: HistoryConversation) => {
    event.preventDefault();
    if (busy || operation.current) return;
    returnFocus.current = event.currentTarget;
    const rect = event.currentTarget.getBoundingClientRect();
    const mouse = 'clientX' in event && (event.clientX !== 0 || event.clientY !== 0);
    setMenu({ item, x: mouse ? event.clientX : rect.left + 20, y: mouse ? event.clientY : rect.bottom });
  };

  const copyText = async (text: string) => {
    if (!navigator.clipboard?.writeText) throw new Error('剪贴板不可用');
    await navigator.clipboard.writeText(text);
  };

  const act = async (action: 'pin' | 'share' | 'copy') => {
    if (!menu || busy || operation.current) return;
    const selected = menu.item;
    operation.current = true; setWorking(true); setNotice(''); setError(''); closeMenu(true);
    try {
      const path = `/api/agent/conversations/${encodeURIComponent(selected.conversation_id)}`;
      if (action === 'pin') {
        const response = await apiFetch(`${path}/pin`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pinned: !selected.pinned_at }), signal: AbortSignal.timeout(15000) });
        if (!response.ok) throw new Error(await responseMessage(response, '置顶保存失败，请重试。'));
        const result: { conversation_id: string; pinned_at: string | null } = await response.json();
        onPinUpdated(result.conversation_id, result.pinned_at);
        setNotice(result.pinned_at ? '已置顶，星标记录将显示在最前面。' : '已取消置顶。');
      } else {
        const response = await apiFetch(`${path}/export`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ purpose: action }), signal: AbortSignal.timeout(15000) });
        if (!response.ok) throw new Error(await responseMessage(response, '无法读取这条问答记录。'));
        const result: ExportText = await response.json();
        if (typeof result.text !== 'string' || !result.text.trim()) throw new Error('问答文本为空，请重试。');
        if (action === 'share') { setDialogNotice(''); setShare(result); }
        else {
          try { await copyText(result.text); setNotice('已复制这条对话的问答、引用和风险说明。'); }
          catch { setDialogNotice('未能访问剪贴板，请点击复制重试，或选中文本手动复制。'); setShare(result); }
        }
      }
    } catch (reason) {
      setError(reason instanceof Error && !['TimeoutError', 'AbortError', 'TypeError'].includes(reason.name) ? reason.message : '连接中断或超时，请刷新核对结果后重试。');
    } finally { operation.current = false; setWorking(false); }
  };

  const menuKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') || []);
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    } else if (event.key === 'Escape' || event.key === 'Tab') {
      event.preventDefault(); closeMenu(true);
    }
  };

  const askDelete = () => {
    if (!menu || busy || operation.current) return;
    const selected = menu.item;
    closeMenu(true); setError(''); setNotice(''); setDeleteError(''); setPendingDelete(selected);
  };

  const confirmDelete = async () => {
    if (!pendingDelete || busy || operation.current) return;
    const selectedId = pendingDelete.conversation_id;
    operation.current = true; setWorking(true); setDeleteError('');
    try {
      const response = await apiFetch(`/api/agent/conversations/${encodeURIComponent(selectedId)}`, { method: 'DELETE', signal: AbortSignal.timeout(15000) });
      if (!response.ok) throw new Error(await responseMessage(response, '删除失败，原记录仍保留，请重试。'));
      onDeleted(selectedId);
      setPendingDelete(null);
      setNotice('已从历史问答库移除该对话。原始记录与审计仍保留在本地后端。');
    } catch (reason) {
      setDeleteError(reason instanceof Error && !['TimeoutError', 'AbortError', 'TypeError'].includes(reason.name) ? reason.message : '连接中断或超时，暂未确认删除结果；可重试或刷新核对。');
    } finally { operation.current = false; setWorking(false); }
  };

  const download = () => {
    if (!share) return;
    const url = URL.createObjectURL(new Blob(['\uFEFF', share.text], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = share.filename;
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setDialogNotice('已发起文本下载。请确认内容后，通过你信任的渠道分享。');
  };

  return <>
    <div ref={listRef} className="conversation-list" aria-busy={working}>
      {!items.length && <p>还没有历史对话。每次问答都会保存引用、Token和审计记录。</p>}
      {!!items.length && <p className="history-menu-hint">右键记录：置顶、分享、复制、删除</p>}
      {sortHistory(items).map((item) => <button key={item.conversation_id} type="button" disabled={busy || working}
        className={activeId === item.conversation_id ? 'active' : ''}
        aria-haspopup="menu" aria-controls={menuId} aria-expanded={menu?.item.conversation_id === item.conversation_id}
        title={`${item.title}${item.pinned_at ? '（已置顶）' : ''} · 右键或Shift+F10打开菜单`}
        onClick={() => { setError(''); void onSelect(item.conversation_id).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : '无法读取对话')); }}
        onContextMenu={(event) => openMenu(event, item)}
        onKeyDown={(event) => { if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) openMenu(event, item); }}>
        <i>{item.linked_task_id ? 'CT' : 'RAG'}</i><span><strong>{item.title}</strong><small>{date(item.last_message_at)} · {item.message_count}条</small></span>
        {item.pinned_at && <em className="history-star" aria-label="已置顶">★</em>}
      </button>)}
    </div>
    {working && <p className="history-action-notice" role="status">正在处理所选问答…</p>}
    {notice && <p className="history-action-notice" role="status">{notice}</p>}
    {error && <p className="history-action-error" role="alert">{error}</p>}
    <div ref={menuRef} id={menuId} popover="auto" role="menu" aria-label="历史问答操作" className="history-context-menu"
      onKeyDown={menuKeys} onToggle={(event) => { if (event.newState === 'closed') setMenu(null); }}>
      <button type="button" role="menuitem" disabled={busy || working} onClick={() => void act('pin')}><span aria-hidden="true">{menu?.item.pinned_at ? '★' : '☆'}</span>{menu?.item.pinned_at ? '取消置顶' : '置顶'}</button>
      <button type="button" role="menuitem" disabled={busy || working} onClick={() => void act('share')}><span aria-hidden="true">↗</span>分享</button>
      <button type="button" role="menuitem" disabled={busy || working} onClick={() => void act('copy')}><span aria-hidden="true">⧉</span>复制</button>
      <button type="button" role="menuitem" className="history-delete-action" disabled={busy || working} onClick={askDelete}><span aria-hidden="true">×</span>删除</button>
    </div>
    {pendingDelete && <dialog ref={deleteDialogRef} className="history-share-dialog history-delete-dialog" aria-labelledby={deleteTitleId} aria-describedby={deleteDescriptionId}
      onCancel={(event) => { if (operation.current) event.preventDefault(); else setPendingDelete(null); }}>
      <header><h2 id={deleteTitleId}>删除这条问答记录？</h2></header>
      <h3>{pendingDelete.title}</h3>
      <p id={deleteDescriptionId}>确认后，这条对话将从历史问答库移除，不能再从普通问答入口访问。{pendingDelete.conversation_id === activeId ? '当前聊天区将回到新对话。' : '不会影响当前查看的其他对话。'}关联CT分析、累计Token用量及已下载的文件不受影响。</p>
      <p>本次为软删除：后端保留原始记录与审计，并非永久清除；目前没有界面恢复入口。</p>
      {deleteError && <p className="history-delete-error" role="alert">{deleteError}</p>}
      <footer><button ref={cancelDeleteRef} type="button" disabled={working} onClick={() => setPendingDelete(null)}>取消</button><button type="button" className="history-delete-confirm" disabled={working || busy} onClick={() => void confirmDelete()}>{working ? '正在删除…' : '确认删除'}</button></footer>
    </dialog>}
    {share && <dialog ref={dialogRef} className="history-share-dialog" aria-labelledby={dialogTitleId} onCancel={() => setShare(null)}>
      <header><h2 id={dialogTitleId}>分享问答记录</h2><button type="button" aria-label="关闭分享窗口" onClick={() => setShare(null)}>×</button></header>
      <h3>{share.title}</h3>
      <p>仅准备当前所选对话的文本，不生成公开链接，也不会自动发送给他人。已进行常见身份信息脱敏，不附带账号资料和来源文件路径字段；分享前仍请检查患者隐私。</p>
      <textarea ref={previewRef} readOnly aria-label="问答分享文本预览" value={share.text} />
      {dialogNotice && <p role="status">{dialogNotice}</p>}
      <footer><button type="button" onClick={() => setShare(null)}>取消</button><button type="button" onClick={download}>下载文本</button><button type="button" className="history-share-primary" onClick={() => { void copyText(share.text).then(() => setDialogNotice('问答文本已复制，可粘贴后分享。')).catch(() => { previewRef.current?.focus(); previewRef.current?.select(); setDialogNotice('剪贴板不可用，已选中文本，请按Ctrl+C或使用系统复制。'); }); }}>复制分享内容</button></footer>
    </dialog>}
  </>;
}
