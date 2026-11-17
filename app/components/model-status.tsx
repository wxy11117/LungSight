'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch } from '../auth-client';
import WorkbenchIcon from './workbench-icon';

type Status = { model_ready: boolean; models_loaded: number; device: string; model_error: string | null };
export function useModelStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const inFlight = useRef(false);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (inFlight.current) return;
    inFlight.current = true; setChecking(true);
    try {
      const response = await apiFetch('/api/health', { cache: 'no-store', signal });
      if (!response.ok) throw new Error();
      const value = await response.json() as Status;
      if (!signal?.aborted) { setStatus(value); setError(''); }
    } catch { if (!signal?.aborted) { setStatus(null); setError('本地服务暂时无法连接，请确认软件已启动。'); } }
    finally { inFlight.current = false; if (!signal?.aborted) setChecking(false); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const initial = window.setTimeout(() => void refresh(controller.signal), 0);
    const timer = window.setInterval(() => void refresh(controller.signal), 15000);
    return () => { controller.abort(); window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);
  return { status, error, checking, refresh };
}

export function ModelStatusNotice({ status, error, checking, refresh, compact = false }: ReturnType<typeof useModelStatus> & { compact?: boolean }) {
  return <section className={`model-status ${compact ? 'is-compact' : ''}`} data-state={error || status && !status.model_ready ? 'warning' : status?.model_ready ? 'ready' : 'loading'} aria-label="本地影像模型状态" role="status" aria-busy={checking}>
    <span className="model-status-symbol"><WorkbenchIcon name={status?.model_ready ? 'shield' : 'scan'} size={21}/></span>
    <div><strong>{error ? '本地服务未连接' : status?.model_ready ? '本地模型已就绪' : status ? '影像分析暂不可用' : '正在连接本地模型'}</strong><span>{status ? `${status.models_loaded} / 5 个权重 · ${status.device.toUpperCase()}` : '正在检查运行状态…'}</span></div>
    {(error || status?.model_error) && <p>{error || status?.model_error}</p>}
    <button type="button" disabled={checking} aria-label="重新检查本地模型" title="重新检查本地模型" onClick={() => void refresh()}><WorkbenchIcon name="refresh" className={checking ? 'wb-spin' : ''}/><span>{checking ? '检查中' : '重新检查'}</span></button>
  </section>;
}
