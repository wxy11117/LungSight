'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import ImageViewer from '../components/image-viewer';
import { confirmUnsavedChanges } from '../components/unsaved-changes';
import CaseReviewForm from '../components/case-review-form';
import BackToAgent from '../back-to-agent';
import { apiBaseUrl, apiFetch, responseMessage } from '../auth-client';

type Detail = {
  task_id: string; created_at: string; updated_at: string; status: string;
  input: { file_name: string; format: string; sha256: string; image_size: [number, number] };
  model: { name: string; version: string; folds: number; device: string; inference_ms: number };
  prediction: { top_class: string; top_class_cn: string; probabilities: Record<string, number> };
  reliability: { level: string; fold_agreement: string; warnings: string[] };
  quality_control: { status: string; warnings: string[]; metrics: Record<string, number> };
  priority: { level: string; label_cn: string; reasons: string[] };
  attention: { available: boolean; method: string; scope?: string };
  review: null | { reviewer_name: string; decision: string; corrected_class_cn: string | null; comment: string; reviewed_at: string };
};
type Audit = { event_id: number; event_type: string; from_status: string | null; to_status: string | null; actor: string; created_at: string };
type Evidence = { query_id: string; question: string; support_level: string; answer: string; evidence: { citation_id: string; title: string; excerpt: string; locator: string }[]; created_at: string };
type SeriesContext = { series_id: string | null; case_name?: string; items: { task_id: string; file_name: string; status: string }[] };
const classNames: Record<string, string> = { adenocarcinoma: '腺癌', large_cell_carcinoma: '大细胞癌', normal: '正常肺部', squamous_cell_carcinoma: '鳞状细胞癌' };

export default function CaseWorkspace() {
  const [taskId, setTaskId] = useState('');
  const [detail, setDetail] = useState<Detail | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [tab, setTab] = useState<'overview' | 'evidence' | 'review' | 'audit'>('overview');
  const changeTab = (next: typeof tab) => { if (next !== tab && confirmUnsavedChanges()) setTab(next); };
  const [series, setSeries] = useState<SeriesContext>({ series_id: null, items: [] });
  const selected = useRef('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState('');
  const [answerError, setAnswerError] = useState('');
  const [includeInReport, setIncludeInReport] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (id: string) => {
    if (!id) { setError('缺少病例编号，请从病例库选择一个病例。'); return; }
    setError('');
    try {
      const [detailResponse, auditResponse, evidenceResponse, seriesResponse] = await Promise.all([
        apiFetch(`/api/tasks/${encodeURIComponent(id)}`, { cache: 'no-store' }),
        apiFetch(`/api/tasks/${encodeURIComponent(id)}/audit`, { cache: 'no-store' }),
        apiFetch(`/api/tasks/${encodeURIComponent(id)}/evidence/history`, { cache: 'no-store' }),
        apiFetch(`/api/tasks/${encodeURIComponent(id)}/series-context`, { cache: 'no-store' }),
      ]);
      if (!detailResponse.ok) throw new Error(await responseMessage(detailResponse, '病例读取失败'));
      const nextDetail = await detailResponse.json() as Detail;
      const nextAudit = auditResponse.ok ? (await auditResponse.json() as { items: Audit[] }).items : [];
      const nextEvidence = evidenceResponse.ok ? (await evidenceResponse.json() as { items: Evidence[] }).items : [];
      const nextSeries = seriesResponse.ok ? await seriesResponse.json() as SeriesContext : { series_id: null, items: [] };
      if (selected.current !== id) return;
      setDetail(nextDetail); setAudit(nextAudit); setEvidence(nextEvidence); setSeries(nextSeries);

    } catch (reason) { if (selected.current === id) setError(reason instanceof Error ? reason.message : '病例读取失败'); }
  }, []);
  useEffect(() => { const id = new URLSearchParams(window.location.search).get('task') || ''; const timer = window.setTimeout(() => { selected.current = id; setTaskId(id); void load(id); }, 0); return () => window.clearTimeout(timer); }, [load]);


  const selectTask = (id: string) => {
    if (!id || id === selected.current || !confirmUnsavedChanges()) return;
    selected.current = id; setTaskId(id); setDetail(null); setAudit([]); setEvidence([]); setAnswer(''); setAnswerError(''); setAsking(false);
    window.history.replaceState(null, '', `/case?task=${encodeURIComponent(id)}`);
    void load(id);
  };
  const ask = async (question: string) => {
    const id = taskId; if (asking) return; setAsking(true); setAnswer(''); setAnswerError('');
    try {
      const response = await apiFetch(`/api/tasks/${encodeURIComponent(id)}/evidence/query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, include_in_report: includeInReport }) });
      if (!response.ok) throw new Error(await responseMessage(response, '解释生成失败，请检查模型服务设置'));
      const payload = await response.json() as { answer: string };
      if (selected.current !== id) return;
      setAnswer(payload.answer); void load(id);
    } catch (reason) { if (selected.current === id) setAnswerError(reason instanceof Error ? reason.message : '解释生成失败'); }
    finally { if (selected.current === id) setAsking(false); }
  };
  const currentIndex = Math.max(0, series.items.findIndex(item => item.task_id === taskId));

  return <main className="case-workspace-shell">
    <header className="settings-topbar"><a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>CASE WORKSPACE</small></span></a><div><a href="/cases" className="case-header-link">病例库</a><BackToAgent /></div></header>
    {error && <section className="case-workspace-error"><h1>无法打开病例工作区</h1><p>{error}</p><a href="/cases">返回病例库</a></section>}
    {!error && !detail && <section className="case-workspace-loading">正在加载病例、证据与审计记录…</section>}
    {detail && <>
      <section className="case-workspace-heading"><div><span>CASE · {detail.status}</span><h1>{detail.task_id}</h1><p>{detail.input.file_name} · {detail.input.image_size.join(' × ')} · {new Date(detail.created_at).toLocaleString('zh-CN')}</p></div><div><a href={`/agent?task=${encodeURIComponent(taskId)}`}>打开CT综合对话</a><a href={`${apiBaseUrl}/api/tasks/${encodeURIComponent(taskId)}/report`}>下载结构化报告</a></div></section>
      <section className="case-context-bar"><span>{detail.review ? '下一步：查看依据并导出报告' : '下一步：查看影像与质量提示，填写本切片复核意见'}</span>{series.items.length > 1 && <select aria-label="选择病例内切片" value={taskId} onChange={event => selectTask(event.target.value)}>{series.items.map((item,index) => <option key={item.task_id} value={item.task_id}>{index + 1}. {item.file_name}</option>)}</select>}</section>
      <section className="case-quick-actions"><span>围绕当前切片提问</span><button disabled={asking} onClick={() => void ask('请解释当前CT模型输出的可靠性、拒判状态和需要人工复核的事项，不做诊断。')}>解释复核重点</button><button disabled={asking} onClick={() => void ask('请根据当前CT结构化质控记录，解释影像质量提示与当前分析的局限。')}>解释质量提示</button><label><input type="checkbox" checked={includeInReport} onChange={event => setIncludeInReport(event.target.checked)} /> 本次问答附入报告</label></section>
      {(asking || answer || answerError) && <section className="case-quick-answer" aria-live="polite">{asking ? <p>正在检索资料、生成解释并核验引用…</p> : <p>{answer}</p>}{answerError && <p role="alert">{answerError} <a href="/settings">打开服务设置</a></p>}{answer && <button onClick={() => changeTab('evidence')}>展开关联证据</button>}</section>}
      <nav className="case-workspace-tabs" aria-label="病例工作区栏目"><button className={tab === 'overview' ? 'active' : ''} onClick={() => changeTab('overview')}>影像与分析</button><button className={tab === 'evidence' ? 'active' : ''} onClick={() => changeTab('evidence')}>AI解释与证据 <i>{evidence.length}</i></button><button className={tab === 'review' ? 'active' : ''} onClick={() => changeTab('review')}>医生复核</button><button className={tab === 'audit' ? 'active' : ''} onClick={() => changeTab('audit')}>审计记录 <i>{audit.length}</i></button></nav>
      {tab === 'overview' && <section className="case-overview-grid">
        <article className="case-image-card"><ImageViewer src={`${apiBaseUrl}/api/tasks/${encodeURIComponent(taskId)}/image`} attentionSrc={detail.attention.available ? `${apiBaseUrl}/api/tasks/${encodeURIComponent(taskId)}/attention` : undefined} taskId={taskId} title={detail.input.file_name} sliceIndex={currentIndex} sliceCount={Math.max(1, series.items.length)} onSliceChange={index => { const next = series.items[index]; if (next) selectTask(next.task_id); }} /></article>
        <article className="case-model-card"><span>MODEL OUTPUT</span><div className="case-model-top"><h2>{detail.prediction.top_class_cn}</h2><strong>{(detail.prediction.probabilities[detail.prediction.top_class] * 100).toFixed(1)}%</strong></div><p>此数值为内部四分类模型概率，不是患癌概率，也不等于病理诊断。</p><div className="case-probabilities">{Object.entries(detail.prediction.probabilities).map(([key, value]) => <div key={key}><span>{classNames[key] || key}</span><i><em style={{ width: `${value * 100}%` }} /></i><b>{(value * 100).toFixed(1)}%</b></div>)}</div><dl><div><dt>五折一致性</dt><dd>{detail.reliability.fold_agreement}</dd></div><div><dt>可靠性</dt><dd>{detail.reliability.level}</dd></div><div><dt>质控</dt><dd>{detail.quality_control.status}</dd></div><div><dt>推理耗时</dt><dd>{detail.model.inference_ms} ms</dd></div></dl><div className="workbench-notice">{[...detail.quality_control.warnings, ...detail.reliability.warnings].join("；") || "当前未触发工程质量提示，仍需人工核对。"}</div><CaseReviewForm key={taskId} taskId={taskId} review={detail.review} onSaved={() => { if (selected.current === taskId) void load(taskId); }} /></article>
      </section>}
      {tab === 'evidence' && <section className="case-workspace-panel"><header><span>EVIDENCE COLLABORATION</span><h2>AI解释与本地证据</h2><p>对话回答与引用按病例留存。引用来源已核对不代表临床结论已经验证。</p></header><a className="case-panel-primary" href={`/agent?task=${encodeURIComponent(taskId)}`}>继续询问当前病例</a>{!evidence.length && <div className="case-panel-empty">还没有关联此病例的证据问答。</div>}{evidence.map((item) => <article className="case-evidence-record" key={item.query_id}><span>{item.support_level}</span><h3>{item.question}</h3><p>{item.answer}</p><div>{item.evidence.map((source) => <details key={source.citation_id}><summary>{source.citation_id} · {source.title}</summary><blockquote>{source.excerpt}</blockquote><small>{source.locator}</small></details>)}</div></article>)}</section>}
      {tab === 'review' && <section className="case-workspace-panel"><header><h2>当前切片复核记录</h2></header><CaseReviewForm key={taskId} taskId={taskId} review={detail.review} onSaved={() => { if (selected.current === taskId) void load(taskId); }} /></section>}
      {tab === 'audit' && <section className="case-workspace-panel"><header><span>AUDIT TRAIL</span><h2>审计记录</h2><p>记录病例创建、分析、问答和复核状态变化。</p></header><div className="case-audit-list">{audit.map((item) => <article key={item.event_id}><i /><div><b>{item.event_type}</b><p>{item.from_status || '开始'} → {item.to_status || '完成'} · {item.actor}</p></div><time>{new Date(item.created_at).toLocaleString('zh-CN')}</time></article>)}</div></section>}
    </>}
  </main>;
}
