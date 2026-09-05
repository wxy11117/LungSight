'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { apiFetch, responseMessage } from '../auth-client';
import { menuPosition } from '../agent/history-actions';
import { sortCases } from './case-actions';
import type { CaseTask } from './case-actions';

type MenuTarget = { item: CaseTask; x: number; y: number };
type Props = {
  items: CaseTask[];
  loading?: boolean;
  archived?: boolean;
  emptyText?: string;
  onRefresh: () => Promise<void>;
};

const statusName: Record<string, string> = {
  WAITING_FOR_REVIEW: '待复核', CONFIRMED: '已确认', CORRECTED: '已修正', UNDETERMINED: '无法判断',
};

export default function CaseTable({ items, loading = false, archived = false, emptyText, onRefresh }: Props) {
  const menuRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const operation = useRef(false);
  const [menu, setMenu] = useState<MenuTarget | null>(null);
  const [pendingDelete, setPendingDelete] = useState<CaseTask | null>(null);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const menuId = useId();
  const titleId = useId();
  const descriptionId = useId();

  const closeMenu = useCallback((restore = false) => {
    menuRef.current?.hidePopover();
    setMenu(null);
    if (restore) returnFocus.current?.focus({ preventScroll: true });
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
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => { window.removeEventListener('resize', close); window.removeEventListener('scroll', close, true); };
  }, [menu, closeMenu]);

  useEffect(() => {
    if (!pendingDelete) return;
    const dialog = dialogRef.current;
    dialog?.showModal();
    cancelRef.current?.focus();
    return () => {
      dialog?.close();
      if (returnFocus.current?.isConnected) returnFocus.current.focus({ preventScroll: true });
    };
  }, [pendingDelete]);

  const openMenu = (event: MouseEvent<HTMLElement> | KeyboardEvent<HTMLElement>, item: CaseTask) => {
    event.preventDefault();
    if (operation.current) return;
    returnFocus.current = event.currentTarget;
    const rect = event.currentTarget.getBoundingClientRect();
    const mouse = 'clientX' in event && (event.clientX !== 0 || event.clientY !== 0);
    setMenu({ item, x: mouse ? event.clientX : rect.right - 24, y: mouse ? event.clientY : rect.bottom });
  };

  const act = async (action: 'STAR' | 'UNSTAR' | 'ARCHIVE' | 'RESTORE') => {
    if (!menu || operation.current) return;
    const selected = menu.item;
    operation.current = true; setWorking(true); setNotice(''); setError(''); closeMenu(true);
    try {
      const response = await apiFetch(`/api/tasks/${encodeURIComponent(selected.task_id)}/library`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }), signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error(await responseMessage(response, '病例操作失败，请重试。'));
      await onRefresh();
      const messages = { STAR: '病例已加星并移到列表前方。', UNSTAR: '已取消病例星标。', ARCHIVE: '病例已移入设置中心的归档模块。', RESTORE: '病例已恢复到病例库。' };
      setNotice(messages[action]);
    } catch (reason) {
      setError(reason instanceof Error && !['TimeoutError', 'AbortError', 'TypeError'].includes(reason.name) ? reason.message : '连接中断或超时，请刷新后核对病例状态。');
    } finally { operation.current = false; setWorking(false); }
  };

  const askDelete = () => {
    if (!menu || operation.current) return;
    const selected = menu.item;
    closeMenu(true); setNotice(''); setError(''); setPendingDelete(selected);
  };

  const confirmDelete = async () => {
    if (!pendingDelete || operation.current) return;
    operation.current = true; setWorking(true); setError('');
    try {
      const response = await apiFetch(`/api/tasks/${encodeURIComponent(pendingDelete.task_id)}`, { method: 'DELETE', signal: AbortSignal.timeout(15000) });
      if (!response.ok) throw new Error(await responseMessage(response, '永久删除失败，病例仍被保留。'));
      setPendingDelete(null);
      await onRefresh();
      setNotice('病例记录及其受管影像已永久删除。');
    } catch (reason) {
      setError(reason instanceof Error && !['TimeoutError', 'AbortError', 'TypeError'].includes(reason.name) ? reason.message : '连接中断或超时，暂未确认删除结果；请刷新核对。');
    } finally { operation.current = false; setWorking(false); }
  };

  const menuKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') || []);
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    } else if (event.key === 'Escape' || event.key === 'Tab') { event.preventDefault(); closeMenu(true); }
  };

  return <>
    {(notice || error) && <p className={error ? 'case-action-error' : 'case-action-notice'} role={error ? 'alert' : 'status'}>{error || notice}</p>}
    <div className="case-table" role="table" aria-label={archived ? '已归档病例' : '病例记录'} aria-busy={working || loading}>
      <div className="case-table-head" role="row"><span>病例与文件</span><span>模型输出</span><span>可靠性</span><span>状态</span><span>{archived ? '归档时间' : '时间'}</span><span>操作</span></div>
      {loading && <p className="case-table-empty">正在读取病例记录…</p>}
      {!loading && !items.length && <p className="case-table-empty">{emptyText || '没有符合当前条件的病例。'}</p>}
      {sortCases(items).map((item) => <article key={item.task_id} role="row" tabIndex={0}
        className={item.starred_at ? 'starred' : ''}
        title={`${item.task_id}${item.starred_at ? '（已加星）' : ''} · 右键或Shift+F10打开菜单`}
        onContextMenu={(event) => openMenu(event, item)}
        onKeyDown={(event) => { if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) openMenu(event, item); }}>
        <span><b>{item.starred_at && <em className="case-star" aria-label="已加星">★</em>}{item.task_id}</b><small>{item.file_name}</small></span>
        <span><b>{item.corrected_class_cn || item.top_class_cn}</b><small>{(item.top_probability * 100).toFixed(1)}% · 模型输出</small></span>
        <span><b>{item.fold_agreement}</b><small>{item.reliability_level}</small></span>
        <span><i className={item.status.toLowerCase()}>{statusName[item.status] || item.status}</i><small>{item.quality_status}</small></span>
        <time>{new Date(archived && item.archived_at ? item.archived_at : item.created_at).toLocaleString('zh-CN')}</time>
        <span className="case-row-actions"><a href={`/case?task=${encodeURIComponent(item.task_id)}`}>打开工作区</a>{!archived && <a href={`/agent?task=${encodeURIComponent(item.task_id)}`}>AI解读</a>}<button type="button" aria-haspopup="menu" aria-controls={menuId} aria-expanded={menu?.item.task_id === item.task_id} aria-label={`打开${item.task_id}操作菜单`} onClick={(event) => openMenu(event, item)}>•••</button></span>
      </article>)}
    </div>
    <div ref={menuRef} id={menuId} popover="auto" role="menu" aria-label="病例操作" className="case-context-menu" onKeyDown={menuKeys} onToggle={(event) => { if (event.newState === 'closed') setMenu(null); }}>
      <button type="button" role="menuitem" disabled={working} onClick={() => void act(menu?.item.starred_at ? 'UNSTAR' : 'STAR')}><span aria-hidden="true">{menu?.item.starred_at ? '★' : '☆'}</span>{menu?.item.starred_at ? '取消星标' : '加星标'}</button>
      <button type="button" role="menuitem" disabled={working} onClick={() => void act(archived ? 'RESTORE' : 'ARCHIVE')}><span aria-hidden="true">{archived ? '↶' : '▣'}</span>{archived ? '恢复到病例库' : '归档病例'}</button>
      <button type="button" role="menuitem" className="case-delete-action" disabled={working} onClick={askDelete}><span aria-hidden="true">×</span>删除病例</button>
    </div>
    {pendingDelete && <dialog ref={dialogRef} className="case-delete-dialog" aria-labelledby={titleId} aria-describedby={descriptionId} onCancel={(event) => { if (operation.current) event.preventDefault(); else setPendingDelete(null); }}>
      <header><span>PERMANENT DELETE</span><h2 id={titleId}>永久删除这个病例？</h2></header>
      <h3>{pendingDelete.task_id} · {pendingDelete.file_name}</h3>
      <p id={descriptionId}>确认后将永久删除病例记录、复核与审计记录、本地原始影像和Grad-CAM文件。相关AI对话会保留，但不再关联此病例。</p>
      <p className="case-delete-warning">此操作无法撤销。若只是暂时不需要查看，请选择“归档病例”。</p>
      {error && <p className="case-action-error" role="alert">{error}</p>}
      <footer><button ref={cancelRef} type="button" disabled={working} onClick={() => setPendingDelete(null)}>取消</button><button type="button" className="danger" disabled={working} onClick={() => void confirmDelete()}>{working ? '正在永久删除…' : '永久删除'}</button></footer>
    </dialog>}
  </>;
}
