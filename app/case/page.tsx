'use client';

import { useCallback, useEffect, useState } from 'react';
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
const classNames: Record<string, string> = { adenocarcinoma: '腺癌', large_cell_carcinoma: '大细胞癌', normal: '正常肺部', squamous_cell_carcinoma: '鳞状细胞癌' };

export default function CaseWorkspace() {
  const [taskId, setTaskId] = useState('');
  const [detail, setDetail] = useState<Detail | null>(null);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [tab, setTab] = useState<'overview' | 'evidence' | 'review' | 'audit'>('overview');
  const [imageMode, setImageMode] = useState<'image' | 'attention'>('image');
  const [error, setError] = useState('');

  const load = useCallback(async (id: string) => {
    if (!id) { setError('缺少病例编号，请从病例库选择一个病例。'); return; }
    setError('');
    try {
      const [detailResponse, auditResponse, evidenceResponse] = await Promise.all([
        apiFetch(`/api/tasks/${encodeURIComponent(id)}`, { cache: 'no-store' }),
        apiFetch(`/api/tasks/${encodeURIComponent(id)}/audit`, { cache: 'no-store' }),
        apiFetch(`/api/tasks/${encodeURIComponent(id)}/evidence/history`, { cache: 'no-store' }),
      ]);
      if (!detailResponse.ok) throw new Error(await responseMessage(detailResponse, '病例读取失败'));
      setDetail(await detailResponse.json());
      if (auditResponse.ok) setAudit((await auditResponse.json() as { items: Audit[] }).items);
      if (evidenceResponse.ok) setEvidence((await evidenceResponse.json() as { items: Evidence[] }).items);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '病例读取失败'); }
  }, []);
  useEffect(() => { const id = new URLSearchParams(window.location.search).get('task') || ''; const timer = window.setTimeout(() => { setTaskId(id); void load(id); }, 0); return () => window.clearTimeout(timer); }, [load]);

  return <main className="case-workspace-shell">
    <header className="settings-topbar"><a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>CASE WORKSPACE</small></span></a><div><a href="/cases" className="case-header-link">病例库</a><BackToAgent /></div></header>
    {error && <section className="case-workspace-error"><h1>无法打开病例工作区</h1><p>{error}</p><a href="/cases">返回病例库</a></section>}
    {!error && !detail && <section className="case-workspace-loading">正在加载病例、证据与审计记录…</section>}
    {detail && <>
      <section className="case-workspace-heading"><div><span>CASE · {detail.status}</span><h1>{detail.task_id}</h1><p>{detail.input.file_name} · {detail.input.image_size.join(' × ')} · {new Date(detail.created_at).toLocaleString('zh-CN')}</p></div><div><a href={`/agent?task=${encodeURIComponent(taskId)}`}>打开CT综合对话</a><a href={`${apiBaseUrl}/api/tasks/${encodeURIComponent(taskId)}/report`}>下载结构化报告</a></div></section>
      <nav className="case-workspace-tabs" aria-label="病例工作区栏目"><button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>影像与分析</button><button className={tab === 'evidence' ? 'active' : ''} onClick={() => setTab('evidence')}>AI解释与证据 <i>{evidence.length}</i></button><button className={tab === 'review' ? 'active' : ''} onClick={() => setTab('review')}>医生复核</button><button className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}>审计记录 <i>{audit.length}</i></button></nav>
      {tab === 'overview' && <section className="case-overview-grid">
        <article className="case-image-card"><header><div><span>IMAGE VIEWER</span><b>{imageMode === 'image' ? '原始CT' : 'Grad-CAM'}</b></div><div><button className={imageMode === 'image' ? 'active' : ''} onClick={() => setImageMode('image')}>原始CT</button><button disabled={!detail.attention.available} className={imageMode === 'attention' ? 'active' : ''} onClick={() => setImageMode('attention')}>Grad-CAM</button></div></header><img key={`${taskId}-${imageMode}-${detail.updated_at}`} src={`${apiBaseUrl}/api/tasks/${encodeURIComponent(taskId)}/${imageMode === 'attention' ? 'attention' : 'image'}?v=${encodeURIComponent(detail.updated_at)}`} alt={imageMode === 'image' ? '待复核二维CT' : '模型关注区域可视化'} /><footer>二维切片 · 本地记录 · 非DICOM诊断阅片器</footer></article>
        <article className="case-model-card"><span>MODEL OUTPUT</span><div className="case-model-top"><h2>{detail.prediction.top_class_cn}</h2><strong>{(detail.prediction.probabilities[detail.prediction.top_class] * 100).toFixed(1)}%</strong></div><p>此数值为内部四分类模型概率，不是患癌概率，也不等于病理诊断。</p><div className="case-probabilities">{Object.entries(detail.prediction.probabilities).map(([key, value]) => <div key={key}><span>{classNames[key] || key}</span><i><em style={{ width: `${value * 100}%` }} /></i><b>{(value * 100).toFixed(1)}%</b></div>)}</div><dl><div><dt>五折一致性</dt><dd>{detail.reliability.fold_agreement}</dd></div><div><dt>可靠性</dt><dd>{detail.reliability.level}</dd></div><div><dt>质控</dt><dd>{detail.quality_control.status}</dd></div><div><dt>推理耗时</dt><dd>{detail.model.inference_ms} ms</dd></div></dl><a href={`/review?task=${encodeURIComponent(taskId)}`}>进入完整医生复核 →</a></article>
      </section>}
      {tab === 'evidence' && <section className="case-workspace-panel"><header><span>EVIDENCE COLLABORATION</span><h2>AI解释与本地证据</h2><p>对话回答与引用按病例留存。引用来源已核对不代表临床结论已经验证。</p></header><a className="case-panel-primary" href={`/agent?task=${encodeURIComponent(taskId)}`}>继续询问当前病例</a>{!evidence.length && <div className="case-panel-empty">还没有关联此病例的证据问答。</div>}{evidence.map((item) => <article className="case-evidence-record" key={item.query_id}><span>{item.support_level}</span><h3>{item.question}</h3><p>{item.answer}</p><div>{item.evidence.map((source) => <small key={source.citation_id}><b>{source.citation_id}</b>{source.title} · {source.locator}</small>)}</div></article>)}</section>}
      {tab === 'review' && <section className="case-workspace-panel"><header><span>CLINICIAN REVIEW</span><h2>医生复核</h2></header>{detail.review ? <article className="case-review-summary"><b>{detail.review.corrected_class_cn || detail.prediction.top_class_cn}</b><p>{detail.review.comment || '未填写复核备注'}</p><small>{detail.review.reviewer_name} · {new Date(detail.review.reviewed_at).toLocaleString('zh-CN')}</small></article> : <div className="case-panel-empty">该病例尚未完成医生复核。模型输出只能作为研究性辅助信息。</div>}<a className="case-panel-primary" href={`/review?task=${encodeURIComponent(taskId)}`}>{detail.review ? '查看或更新复核记录' : '进入医生复核'}</a></section>}
      {tab === 'audit' && <section className="case-workspace-panel"><header><span>AUDIT TRAIL</span><h2>审计记录</h2><p>记录病例创建、分析、问答和复核状态变化。</p></header><div className="case-audit-list">{audit.map((item) => <article key={item.event_id}><i /><div><b>{item.event_type}</b><p>{item.from_status || '开始'} → {item.to_status || '完成'} · {item.actor}</p></div><time>{new Date(item.created_at).toLocaleString('zh-CN')}</time></article>)}</div></section>}
    </>}
  </main>;
}
