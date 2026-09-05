'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import BackToAgent from '../back-to-agent';
import { apiFetch, responseMessage } from '../auth-client';
import CaseTable from './case-table';
import type { CaseTask } from './case-actions';

type Counts = { total: number; waiting: number; reviewed: number; flagged: number; urgent: number; archived: number };

export default function CaseLibrary() {
  const [items, setItems] = useState<CaseTask[]>([]);
  const [counts, setCounts] = useState<Counts>({ total: 0, waiting: 0, reviewed: 0, flagged: 0, urgent: 0, archived: 0 });
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const response = await apiFetch('/api/tasks?limit=200', { cache: 'no-store' });
      if (!response.ok) throw new Error(await responseMessage(response, '病例库读取失败'));
      const payload = await response.json() as { items: CaseTask[]; counts: Counts };
      setItems(payload.items); setCounts(payload.counts);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '病例库读取失败'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);

  const filtered = useMemo(() => items.filter((item) => {
    const matchesQuery = !query.trim() || `${item.task_id} ${item.file_name} ${item.top_class_cn} ${item.reviewer_name || ''}`.toLowerCase().includes(query.trim().toLowerCase());
    return matchesQuery && (!status || item.status === status);
  }), [items, query, status]);

  return <main className="case-library-shell">
    <header className="settings-topbar"><a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>CASE LIBRARY</small></span></a><BackToAgent /></header>
    <section className="case-library-content">
      <div className="case-library-heading"><div><span>CLINICAL WORKSPACE</span><h1>病例库</h1><p>集中检索CT分析任务、复核状态和结构化报告。模型输出不等于临床诊断。</p></div><a href="/analysis">＋ 新建CT分析</a></div>
      <div className="case-stats"><article><span>全部病例</span><b>{counts.total}</b></article><article><span>等待复核</span><b>{counts.waiting}</b></article><article><span>已经复核</span><b>{counts.reviewed}</b></article><article><span>质控提示</span><b>{counts.flagged}</b></article></div>
      <div className="case-toolbar"><label><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索病例编号、文件名或分类" aria-label="搜索病例" /></label><select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="按状态筛选"><option value="">全部状态</option><option value="WAITING_FOR_REVIEW">等待复核</option><option value="CONFIRMED">已确认</option><option value="CORRECTED">已修正</option><option value="UNDETERMINED">无法判断</option></select><button type="button" onClick={() => void load()}>刷新</button></div>
      {error && <p className="case-library-error" role="alert">{error}</p>}
      <p className="case-menu-hint">右键病例可加星标、归档或删除；已归档病例可在设置中心查看和恢复。</p>
      <CaseTable items={filtered} loading={loading} onRefresh={load} />
    </section>
  </main>;
}
