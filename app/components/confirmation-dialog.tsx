'use client';

import { useEffect, useRef, useSyncExternalStore } from 'react';
import WorkbenchIcon from './workbench-icon';

type Confirmation = { title: string; description: string; confirmLabel?: string; cancelLabel?: string; destructive?: boolean };
type Pending = { options: Confirmation; resolve: (value: boolean) => void };
let pending: Pending | null = null;
const subscribers = new Set<() => void>();
const subscribe = (listener: () => void) => { subscribers.add(listener); return () => { subscribers.delete(listener); }; };
const getSnapshot = () => pending;
const getServerSnapshot = () => null;

export function confirmAction(options: Confirmation): Promise<boolean> {
  // Repeated clicks cannot stack dialogs or silently accept a second action.
  if (pending || !subscribers.size) return Promise.resolve(false);
  return new Promise(resolve => { pending = { options, resolve }; subscribers.forEach(listener => listener()); });
}

function finish(accepted: boolean) {
  const current = pending;
  pending = null;
  subscribers.forEach(listener => listener());
  current?.resolve(accepted);
}

export default function ConfirmationDialog() {
  const request = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (request && !dialog.current?.open) dialog.current?.showModal();
    if (!request && dialog.current?.open) dialog.current?.close();
  }, [request]);
  return <dialog ref={dialog} className="wb-confirm" aria-labelledby="wb-confirm-title" aria-describedby="wb-confirm-description" onCancel={event => { event.preventDefault(); finish(false); }} onClick={event => { if (event.target === event.currentTarget) finish(false); }}>
    {request && <div className="wb-confirm-content">
      <div className={`wb-confirm-symbol ${request.options.destructive ? 'warning' : ''}`}><WorkbenchIcon name={request.options.destructive ? 'info' : 'save'} size={26}/></div>
      <h2 id="wb-confirm-title">{request.options.title}</h2>
      <p id="wb-confirm-description">{request.options.description}</p>
      <div className="wb-confirm-actions"><button type="button" autoFocus onClick={() => finish(false)}>{request.options.cancelLabel || '取消'}</button><button type="button" className={request.options.destructive ? 'danger' : 'primary'} onClick={() => finish(true)}>{request.options.confirmLabel || '确定'}</button></div>
    </div>}
  </dialog>;
}
