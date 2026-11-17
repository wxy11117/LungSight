'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../auth-client';

type Status = { model_ready: boolean; models_loaded: number; device: string; model_error: string | null };
export function useModelStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState('');
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await apiFetch('/api/health', { cache: 'no-store', signal });
      if (!response.ok) throw new Error();
      const value = await response.json() as Status;
      if (!signal?.aborted) { setStatus(value); setError(''); }
    } catch { if (!signal?.aborted) { setStatus(null); setError('本地服务暂时无法连接，请确认软件已启动。'); } }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const initial = window.setTimeout(() => void refresh(controller.signal), 0);
    const timer = window.setInterval(() => void refresh(controller.signal), 15000);
    return () => { controller.abort(); window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);
  return { status, error, refresh };
}

export function ModelStatusNotice({ status, error, refresh }: ReturnType<typeof useModelStatus>) {
  return <section className="model-status" aria-label="本地影像模型状态" role="status">
    <div><strong>{error ? '本地服务未连接' : status?.model_ready ? '本地影像模型已就绪' : status ? '影像分析暂不可用' : '正在检查本地模型…'}</strong><span>{status ? `${status.models_loaded} / 5 个权重 · ${status.device}` : ''}</span></div>
    {(error || status?.model_error) && <p>{error || status?.model_error}</p>}
    <button type="button" onClick={() => void refresh()}>重新检查</button>
  </section>;
}
