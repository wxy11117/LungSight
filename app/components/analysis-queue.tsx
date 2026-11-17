'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch, responseMessage } from '../auth-client';
import { confirmUnsavedChanges } from './unsaved-changes';

export type AnalysisJob<Result> = {
  job_id: string; case_name: string; mode: 'image' | 'dicom'; state: string; error: string;
  total: number; completed: number; failed: number; series_id: string | null; results: Result[];
  items: { ordinal: number; file_name: string; state: string; stage: string; task_id: string; retryable: boolean; error: string }[];
};
export const activeJobStates = new Set(['QUEUED', 'RUNNING', 'CANCELLING']);
const labels: Record<string, string> = { CLEARED: '缓存已释放', DELETED: '已删除', QUEUED: '排队中', RUNNING: '处理中', CANCELLING: '正在取消', CANCELLED: '已取消', SUCCEEDED: '已完成', PARTIAL: '部分完成', FAILED: '未完成', INTERRUPTED: '服务中断', READY: '等待处理', WAITING: '等待处理', READING: '读取影像', QUALITY: '质量检查', INFERENCE: '五折推理', ATTENTION: '生成注意力图', SAVING: '保存结果', DONE: '已保存', INVALID: '输入不适用' };

export function useAnalysisQueue<Result>(onUpdate: (job: AnalysisJob<Result>) => void) {
  const [jobs, setJobs] = useState<AnalysisJob<Result>[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [error, setError] = useState('');
  const [acting, setActing] = useState(false);
  const interacted = useRef(false);
  const callback = useRef(onUpdate);
  useEffect(() => { callback.current = onUpdate; }, [onUpdate]);
  const accept = useCallback((job: AnalysisJob<Result>) => {
    interacted.current = true;
    setSelectedId(job.job_id);
    setJobs(current => [job, ...current.filter(item => item.job_id !== job.job_id)].slice(0, 20));
    callback.current(job);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void apiFetch('/api/analysis-jobs', { signal: controller.signal, cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error(await responseMessage(response, '后台任务读取失败'));
      const payload = await response.json() as { items: AnalysisJob<Result>[] };
      if (controller.signal.aborted) return;
      setJobs(current => [...current, ...payload.items.filter(item => !current.some(existing => existing.job_id === item.job_id))].slice(0, 20));
      const active = payload.items.find(item => activeJobStates.has(item.state)) || payload.items.find(item => item.state === 'INTERRUPTED');
      if (active && !interacted.current) accept(active);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '后台任务读取失败'); });
    return () => controller.abort();
  }, [accept]);
  const job = jobs.find(item => item.job_id === selectedId) || null;
  const jobId = job?.job_id;
  const jobState = job?.state;
  useEffect(() => {
    if (!jobId || !jobState || !activeJobStates.has(jobState)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await apiFetch(`/api/analysis-jobs/${encodeURIComponent(jobId)}`, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error(await responseMessage(response, '进度读取失败，正在重连'));
        const updated = await response.json() as AnalysisJob<Result>;
        if (controller.signal.aborted) return;
        setError(''); accept(updated);
        if (!activeJobStates.has(updated.state)) return;
      } catch (reason) { if (controller.signal.aborted) return; setError(reason instanceof Error ? reason.message : '进度读取失败，正在重连'); }
      timer = setTimeout(() => void poll(), 1500);
    };
    timer = setTimeout(() => void poll(), 500);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [jobId, jobState, accept]); // Keep polling through transient network errors.

  const action = async (operation: 'cancel' | 'retry' | 'clear-inputs') => {
    if (!job || acting) return;
    if (operation === 'clear-inputs' && !window.confirm('释放未完成项的输入缓存后，需要重新选择文件才能分析。已保存的影像结果和报告会保留。确定释放吗？')) return;
    setActing(true); setError('');
    try {
      const response = await apiFetch(`/api/analysis-jobs/${job.job_id}/${operation}`, { method: 'POST' });
      if (!response.ok) throw new Error(await responseMessage(response, '任务操作失败'));
      accept(await response.json() as AnalysisJob<Result>);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '任务操作失败'); }
    finally { setActing(false); }
  };
  return { jobs, job, error, acting, accept, action, clear: () => { interacted.current = true; setSelectedId(''); }, select: (id: string) => { const selected = jobs.find(item => item.job_id === id); if (selected && id !== selectedId && confirmUnsavedChanges()) accept(selected); } };
}

export default function AnalysisQueuePanel<Result>({ queue }: { queue: ReturnType<typeof useAnalysisQueue<Result>> }) {
  const { job, jobs, error, acting } = queue;
  if (!jobs.length && !error) return null;
  const current = job?.items.find(item => item.state === 'RUNNING');
  return <section className="job-panel" aria-label="后台分析任务">
    <header><div><h2>后台分析任务</h2><p>刷新页面可恢复进度；成功切片保留，重试只处理未完成项。</p></div><select aria-label="选择后台任务" value={job?.job_id || ''} disabled={acting} onChange={event => queue.select(event.target.value)}><option value="" disabled>选择任务</option>{jobs.map(item => <option key={item.job_id} value={item.job_id}>{item.case_name} · {labels[item.state] || item.state}</option>)}</select></header>
    {error && <p role="alert">{error}</p>}
    {job && <><div className="job-stage" role="status"><strong>{labels[job.state]}{current ? ` · ${labels[current.stage]} · ${current.file_name}` : ''}</strong><span>{job.completed} / {job.total} 已保存 · {job.failed} 项失败</span></div><progress aria-label="切片处理进度" value={job.completed + job.failed} max={Math.max(1, job.total)} />
      <div className="job-actions">{activeJobStates.has(job.state) ? <button disabled={acting || job.state === 'CANCELLING'} onClick={() => void queue.action('cancel')}>{job.state === 'CANCELLING' ? '等待当前计算阶段结束…' : '取消剩余处理'}</button> : job.state !== 'SUCCEEDED' && (job.items.some(item => item.retryable) || job.error) ? <button disabled={acting} onClick={() => void queue.action('retry')}>{acting ? '正在恢复…' : '继续 / 重试未完成项'}</button> : null}<a href="/cases">查看已保存结果 →</a></div>
      {!activeJobStates.has(job.state) && job.items.some(item => item.retryable) && <button type="button" disabled={acting} onClick={() => void queue.action('clear-inputs')}>释放未完成项输入缓存</button>}
      {job.error && <p role="alert">{job.error}</p>}<details><summary>逐项进度与失败原因</summary><ul>{job.items.map(item => <li key={item.ordinal}><span>{item.file_name}</span><b>{labels[item.state]}</b><small>{item.error || labels[item.stage]}{item.state === 'FAILED' && !item.retryable ? '（需重新选择文件）' : ''}</small></li>)}</ul></details>
    </>}
  </section>;
}
