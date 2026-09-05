'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import BackToAgent from '../back-to-agent';
import { apiFetch } from '../auth-client';

const apiBaseUrl = process.env.NEXT_PUBLIC_LUNGSIGHT_API_URL ?? 'http://127.0.0.1:8001';
const classes = [
  ['adenocarcinoma', '腺癌'],
  ['large_cell_carcinoma', '大细胞癌'],
  ['normal', '正常肺部'],
  ['squamous_cell_carcinoma', '鳞状细胞癌'],
] as const;

type Counts = { total: number; waiting: number; reviewed: number; flagged: number; urgent: number };
type TaskSummary = {
  task_id: string;
  created_at: string;
  status: string;
  file_name: string;
  top_class: string;
  top_class_cn: string;
  top_probability: number;
  reliability_level: string;
  fold_agreement: string;
  quality_status: string;
  priority: string;
  attention_available: boolean;
  reviewer_name: string | null;
  corrected_class_cn: string | null;
};
type TaskDetail = {
  task_id: string;
  created_at: string;
  updated_at: string;
  status: string;
  input: { file_name: string; format: string; sha256: string; image_size: [number, number] };
  model: { name: string; version: string; folds: number; device: string; inference_ms: number };
  prediction: { top_class: string; top_class_cn: string; probabilities: Record<string, number> };
  reliability: { level: string; fold_agreement: string; warnings: string[] };
  quality_control: {
    status: string;
    warnings: string[];
    metrics: { mean_luminance?: number; contrast_std?: number; edge_variance?: number; exact_duplicate_count?: number };
  };
  priority: { level: string; label_cn: string; reasons: string[] };
  attention: { available: boolean; method: string; scope?: string };
  review: null | {
    reviewer_name: string;
    decision: string;
    corrected_class: string | null;
    corrected_class_cn: string | null;
    comment: string;
    reviewed_at: string;
  };
};
type AuditEvent = { event_id: number; event_type: string; from_status: string | null; to_status: string | null; actor: string; created_at: string };
type EvidenceCard = {
  citation_id: string;
  source_type?: string;
  source_id: string;
  title: string;
  authority: string;
  version: string;
  locator: string;
  page_number: number | null;
  section: string;
  sha256: string;
  excerpt: string;
};
type EvidenceResult = {
  query_id: string;
  conversation_id?: string;
  question: string;
  support_level: 'SUPPORTED' | 'PARTIALLY_SUPPORTED' | 'INSUFFICIENT' | 'REFUSED' | 'MIXED' | 'GENERAL_KNOWLEDGE';
  answer: string;
  evidence: EvidenceCard[];
  limitations: string[];
  include_in_report: boolean;
  created_at: string;
};

const statusLabels: Record<string, string> = {
  WAITING_FOR_REVIEW: '等待复核',
  CONFIRMED: '已确认',
  CORRECTED: '已修正',
  UNDETERMINED: '无法判断',
};

const decisionLabels: Record<string, string> = {
  CONFIRM: '确认模型结果',
  CORRECT: '修正模型结果',
  UNDETERMINED: '无法判断',
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value));
}

export default function ReviewWorkbench() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [counts, setCounts] = useState<Counts>({ total: 0, waiting: 0, reviewed: 0, flagged: 0, urgent: 0 });
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [classFilter, setClassFilter] = useState('');
  const [reliabilityFilter, setReliabilityFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [evidenceResults, setEvidenceResults] = useState<EvidenceResult[]>([]);
  const [evidenceQuestion, setEvidenceQuestion] = useState('');
  const [includeEvidenceInReport, setIncludeEvidenceInReport] = useState(true);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [sourceStats, setSourceStats] = useState({ sources: 0, chunks: 0 });
  const [imageMode, setImageMode] = useState<'original' | 'attention'>('original');
  const [reviewerName, setReviewerName] = useState('');
  const [decision, setDecision] = useState<'CONFIRM' | 'CORRECT' | 'UNDETERMINED'>('CONFIRM');
  const [correctedClass, setCorrectedClass] = useState('adenocarcinoma');
  const [comment, setComment] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const fetchDetail = useCallback(async (taskId: string) => {
    if (!taskId) { setDetail(null); setAuditEvents([]); setEvidenceResults([]); return; }
    const [response, auditResponse, evidenceResponse] = await Promise.all([
      apiFetch(`/api/tasks/${encodeURIComponent(taskId)}`),
      apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/audit`),
      apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/evidence/history`),
    ]);
    if (!response.ok || !auditResponse.ok || !evidenceResponse.ok) throw new Error('无法读取任务详情');
    setDetail(await response.json() as TaskDetail);
    const auditPayload = await auditResponse.json() as { items: AuditEvent[] };
    setAuditEvents(auditPayload.items);
    const evidencePayload = await evidenceResponse.json() as { items: EvidenceResult[] };
    setEvidenceResults(evidencePayload.items);
  }, []);

  const fetchTasks = useCallback(async (preferredId?: string) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (classFilter) params.set('class_name', classFilter);
      if (reliabilityFilter) params.set('reliability', reliabilityFilter);
      if (priorityFilter) params.set('priority', priorityFilter);
      const response = await apiFetch(`/api/tasks?${params}`);
      if (!response.ok) throw new Error('无法读取本地任务列表');
      const payload = await response.json() as { items: TaskSummary[]; counts: Counts };
      setTasks(payload.items);
      setCounts(payload.counts);
      const requested = preferredId || selectedId || payload.items[0]?.task_id || '';
      setSelectedId(requested);
      await fetchDetail(requested);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '本地推理服务不可用');
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [classFilter, fetchDetail, priorityFilter, reliabilityFilter, selectedId, statusFilter]);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get('task') || undefined;
    const timer = window.setTimeout(() => {
      void fetchTasks(requested);
      void apiFetch('/api/evidence/sources').then(async (response) => {
        if (response.ok) {
          const payload = await response.json() as { counts: { sources: number; chunks: number } };
          setSourceStats(payload.counts);
        }
      });
    }, 0);
    // Initial query is intentionally run once; filters have an explicit apply button.
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectTask = async (taskId: string) => {
    setSelectedId(taskId);
    setImageMode('original');
    setError('');
    try { await fetchDetail(taskId); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '任务读取失败'); }
  };

  const submitReview = async () => {
    if (!detail || !reviewerName.trim()) {
      setError('请填写复核医生姓名或工号');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const response = await apiFetch(`/api/tasks/${encodeURIComponent(detail.task_id)}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision,
          reviewer_name: reviewerName.trim(),
          corrected_class: decision === 'CORRECT' ? correctedClass : null,
          comment,
        }),
      });
      const payload = await response.json().catch(() => null) as TaskDetail | { detail?: string } | null;
      if (!response.ok) throw new Error(payload && 'detail' in payload && payload.detail ? payload.detail : '复核提交失败');
      setDetail(payload as TaskDetail);
      setComment('');
      await fetchTasks(detail.task_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '复核提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const submitEvidenceQuestion = async () => {
    if (!detail || evidenceQuestion.trim().length < 2) {
      setError('请先输入医学或CT解读问题');
      return;
    }
    setEvidenceLoading(true);
    setError('');
    try {
      const response = await apiFetch(`/api/tasks/${encodeURIComponent(detail.task_id)}/evidence/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: evidenceQuestion.trim(), include_in_report: includeEvidenceInReport, conversation_id: evidenceResults[0]?.conversation_id || null }),
      });
      const payload = await response.json().catch(() => null) as EvidenceResult | { detail?: string } | null;
      if (!response.ok) throw new Error(payload && 'detail' in payload && payload.detail ? payload.detail : 'CT综合问答失败');
      setEvidenceResults((current) => [payload as EvidenceResult, ...current]);
      setEvidenceQuestion('');
      await fetchDetail(detail.task_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'CT综合问答失败');
    } finally {
      setEvidenceLoading(false);
    }
  };

  const probabilityRows = useMemo(() => classes.map(([key, label]) => ({
    key, label, value: (detail?.prediction.probabilities[key] ?? 0) * 100,
  })), [detail]);

  return <main className="review-shell">
    <header className="review-topbar">
      <a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>DOCTOR REVIEW WORKBENCH</small></span></a>
      <div><BackToAgent /><span className="local-status"><i /> 安全工作区已连接</span></div>
    </header>

    <section className="review-intro">
      <div><span className="review-eyebrow">HUMAN IN THE LOOP · EVIDENCE AGENT</span><h1>医生复核工作台</h1><p>模型给出概率与解释，循证 Agent 返回可定位来源，最终判断由医生完成。</p></div>
      <div className="review-counts">
        <article><span>全部任务</span><strong>{counts.total}</strong></article>
        <article><span>等待复核</span><strong>{counts.waiting}</strong></article>
        <article><span>已复核</span><strong>{counts.reviewed}</strong></article>
        <article><span>优先队列</span><strong>{counts.urgent}</strong></article>
      </div>
    </section>

    <section className="review-workspace">
      <aside className="task-browser">
        <div className="task-browser-head"><div><span>TASK QUEUE</span><b>病例任务</b></div><button onClick={()=>void fetchTasks()}>刷新 ↻</button></div>
        <div className="task-filters">
          <select aria-label="复核状态" value={statusFilter} onChange={(event)=>setStatusFilter(event.target.value)}>
            <option value="">全部状态</option><option value="WAITING_FOR_REVIEW">等待复核</option><option value="CONFIRMED">已确认</option><option value="CORRECTED">已修正</option><option value="UNDETERMINED">无法判断</option>
          </select>
          <select aria-label="预测类别" value={classFilter} onChange={(event)=>setClassFilter(event.target.value)}>
            <option value="">全部类别</option>{classes.map(([key,label])=><option key={key} value={key}>{label}</option>)}
          </select>
          <select aria-label="可靠性" value={reliabilityFilter} onChange={(event)=>setReliabilityFilter(event.target.value)}>
            <option value="">全部可靠性</option><option value="STABLE">稳定</option><option value="REVIEW_REQUIRED">需重点复核</option>
          </select>
          <select aria-label="复核优先级" value={priorityFilter} onChange={(event)=>setPriorityFilter(event.target.value)}>
            <option value="">全部优先级</option><option value="HIGH_RISK">高风险人工检查</option><option value="PRIORITY">优先复核</option><option value="ROUTINE">普通复核</option>
          </select>
          <button onClick={()=>void fetchTasks()}>应用筛选</button>
        </div>
        <div className="task-list">
          {loading && <p className="empty-state">正在读取本地任务…</p>}
          {!loading && !tasks.length && <p className="empty-state">当前筛选条件下没有任务。</p>}
          {tasks.map((task)=><button key={task.task_id} className={selectedId===task.task_id?'task-row active':'task-row'} onClick={()=>void selectTask(task.task_id)}>
            <span className={`task-state ${task.status.toLowerCase()}`}>{statusLabels[task.status] || task.status}</span><span className={`priority-chip ${task.priority.toLowerCase()}`}>{task.priority === 'HIGH_RISK' ? '高风险' : task.priority === 'PRIORITY' ? '优先' : '普通'}</span>
            <strong>{task.top_class_cn}</strong><em>{(task.top_probability*100).toFixed(1)}%</em>
            <small>{task.task_id} · {formatDate(task.created_at)}</small>
            <i className={task.reliability_level === 'STABLE' ? 'stable' : 'flagged'}>{task.fold_agreement}</i>
          </button>)}
        </div>
      </aside>

      <section className="case-review-panel">
        {error && <div className="review-error">{error}</div>}
        {!detail && !error && <div className="review-placeholder"><span>◎</span><h2>选择一个任务开始复核</h2><p>分析完成的任务会自动进入左侧队列。</p></div>}
        {detail && <>
          <div className="case-review-head"><div><span>CASE DETAIL</span><h2>{detail.task_id}</h2><p>{detail.input.file_name} · {detail.input.image_size[0]} × {detail.input.image_size[1]}</p></div><div><span className={`priority-chip ${detail.priority.level.toLowerCase()}`}>{detail.priority.label_cn}</span><span className={`case-status ${detail.status.toLowerCase()}`}>{statusLabels[detail.status]}</span><a href={`/agent?task=${detail.task_id}`}>打开CT综合对话 ↗</a><a href={`${apiBaseUrl}/api/tasks/${detail.task_id}/report`}>下载结构化报告 ↓</a></div></div>
          <div className="case-review-grid">
            <div className="review-image"><div className="image-mode-switch"><button className={imageMode==='original'?'active':''} onClick={()=>setImageMode('original')}>原始 CT</button><button className={imageMode==='attention'?'active':''} disabled={!detail.attention.available} onClick={()=>setImageMode('attention')}>Grad-CAM</button></div><img src={`${apiBaseUrl}/api/tasks/${detail.task_id}/${imageMode === 'attention' ? 'attention' : 'image'}?v=${encodeURIComponent(detail.updated_at)}`} alt={imageMode === 'attention' ? '五折平均 Grad-CAM 注意力图' : '待复核二维 CT'} /><span>{imageMode === 'attention' ? 'MODEL ATTENTION · NOT LESION SEGMENTATION' : '2D CT · LOCAL RECORD'}</span></div>
            <div className="review-result">
              <span className="review-label">MODEL OUTPUT</span>
              <div className="review-top-result"><div><small>模型内部最高排序（非诊断）</small><strong>{detail.prediction.top_class_cn}</strong></div><b>{Math.max(...probabilityRows.map((item)=>item.value)).toFixed(1)}%</b></div>
              <div className="review-probabilities">{probabilityRows.map((item)=><div key={item.key}><span>{item.label}</span><i><em style={{width:`${item.value}%`}} /></i><b>{item.value.toFixed(1)}%</b></div>)}</div>
              <div className="review-evidence"><span><small>五折一致性</small><b>{detail.reliability.fold_agreement}</b></span><span><small>可靠性</small><b>{detail.reliability.level === 'STABLE' ? '稳定' : '需重点复核'}</b></span><span><small>推理耗时</small><b>{detail.model.inference_ms.toFixed(0)} ms</b></span></div>
              <p className={detail.reliability.warnings.length?'review-warning active':'review-warning'}>{detail.reliability.warnings.length ? detail.reliability.warnings.join('；') : '未触发工程可靠性警告；仍需医生结合临床信息判断。'}</p>
              <div className="qc-summary"><div><span>IMAGE QC AGENT</span><b>{detail.quality_control.status === 'PASS' ? '质控通过' : '质控提示'}</b></div><div className="qc-metrics"><span><small>亮度均值</small><b>{detail.quality_control.metrics.mean_luminance?.toFixed(1) ?? '—'}</b></span><span><small>对比度</small><b>{detail.quality_control.metrics.contrast_std?.toFixed(1) ?? '—'}</b></span><span><small>边缘方差</small><b>{detail.quality_control.metrics.edge_variance?.toFixed(0) ?? '—'}</b></span><span><small>完全重复</small><b>{detail.quality_control.metrics.exact_duplicate_count ?? 0}</b></span></div><p>{detail.quality_control.warnings.length ? detail.quality_control.warnings.join('；') : '尺寸、亮度、对比度、清晰度与重复性检查未触发警告。'}</p></div>
            </div>
          </div>

          <section className="evidence-agent-panel">
            <div className="evidence-agent-head"><div><span>EVIDENCE COLLABORATION AGENT</span><h3>CT综合医学问答</h3><p>结合当前CT结构化结果、本地资料与所选模型的医学知识。原文摘录与模型解读分区显示；模型知识并非实时指南，不替代医生判断。</p></div><div><strong>{sourceStats.sources}</strong><small>核验来源</small><strong>{sourceStats.chunks}</strong><small>证据片段</small></div></div>
            <div className="evidence-prompts">{['为什么最终选择 ResNet18？','模型的性能和置信区间如何？','数据去重为什么重要？','能否证明可在所有医院直接使用？'].map((question)=><button key={question} onClick={()=>setEvidenceQuestion(question)}>{question}</button>)}</div>
            <div className="evidence-query-box"><textarea value={evidenceQuestion} maxLength={500} onChange={(event)=>setEvidenceQuestion(event.target.value)} placeholder="例如：为什么最终采用原始 ResNet18，而没有使用融合模型？" /><div><label><input type="checkbox" checked={includeEvidenceInReport} onChange={(event)=>setIncludeEvidenceInReport(event.target.checked)} /> 加入结构化报告</label><button disabled={evidenceLoading} onClick={()=>void submitEvidenceQuestion()}>{evidenceLoading?'正在综合解读与核对引用…':'生成综合解读 →'}</button></div></div>
            <div className="evidence-results">
              {!evidenceResults.length && <p className="evidence-empty">提出问题后，Agent 将调用主页配置的模型，返回本地摘录、综合医学解读及局限说明，并保存到问答记录。</p>}
              {evidenceResults.map((result)=><article className="evidence-answer" key={result.query_id}>
                <div className="evidence-answer-head"><div><span>Q</span><strong>{result.question}</strong></div><i className={result.support_level.toLowerCase()}>{result.support_level === 'MIXED' ? '本地摘录 + 模型解读' : result.support_level === 'GENERAL_KNOWLEDGE' ? '模型医学知识' : result.support_level === 'SUPPORTED' ? '证据支持' : result.support_level === 'PARTIALLY_SUPPORTED' ? '部分支持' : result.support_level === 'REFUSED' ? '安全拒答' : '证据不足'}</i></div>
                <p>{result.answer}</p>
                {!!result.evidence.length && <div className="evidence-cards">{result.evidence.map((card)=><a key={`${result.query_id}-${card.citation_id}`} href={card.source_type === 'ct-structured-result' ? `/review?task=${encodeURIComponent(card.source_id)}` : `${apiBaseUrl}/api/evidence/sources/${card.source_id}/content`} target="_blank" rel="noreferrer"><div><span>{card.citation_id}</span><strong>{card.title}</strong></div><p>{card.excerpt}</p><footer><span>{card.authority} · {card.version}</span><span>{card.page_number ? `第 ${card.page_number} 页` : card.section}</span></footer><small>{card.locator} · SHA-256 {(card.sha256 || '').slice(0,12)}…</small></a>)}</div>}
                <div className="evidence-limit">{result.limitations.join('；')}{result.include_in_report ? ' · 已加入报告' : ''}</div>
              </article>)}
            </div>
          </section>

          {detail.review ? <section className="review-complete">
            <span>REVIEW COMPLETED</span><h3>{decisionLabels[detail.review.decision]}</h3>
            {detail.review.corrected_class_cn && <strong>医生修正类别：{detail.review.corrected_class_cn}</strong>}
            <p>{detail.review.comment || '未填写补充意见'}</p><small>{detail.review.reviewer_name} · {formatDate(detail.review.reviewed_at)}</small>
          </section> : <section className="review-form">
            <div className="review-form-title"><span>DOCTOR DECISION</span><h3>提交最终复核意见</h3><p>提交后将形成留痕并锁定当前任务。</p></div>
            <div className="decision-options">
              {([['CONFIRM','✓','确认模型结果'],['CORRECT','↻','修正分类'],['UNDETERMINED','?','无法判断']] as const).map(([value,icon,label])=><button key={value} className={decision===value?'active':''} onClick={()=>setDecision(value)}><i>{icon}</i><span>{label}</span></button>)}
            </div>
            <div className="review-fields">
              <label><span>复核医生 / 工号 *</span><input value={reviewerName} maxLength={80} onChange={(event)=>setReviewerName(event.target.value)} placeholder="例如：张医生 / DR-001" /></label>
              {decision === 'CORRECT' && <label><span>修正后的类别 *</span><select value={correctedClass} onChange={(event)=>setCorrectedClass(event.target.value)}>{classes.map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>}
              <label className="comment-field"><span>复核意见</span><textarea value={comment} maxLength={1000} onChange={(event)=>setComment(event.target.value)} placeholder="填写判断依据、需要补充的检查或其他说明…" /></label>
            </div>
            <button className="submit-review" disabled={submitting} onClick={()=>void submitReview()}><span>{submitting?'正在保存复核记录…':'确认并提交复核'}</span><i>→</i></button>
          </section>}
          <section className="audit-timeline"><div><span>AUDIT TRAIL</span><h3>任务审计记录</h3></div>{auditEvents.map((event)=><article key={event.event_id}><i /><div><strong>{event.event_type === 'ANALYSIS_CREATED' ? 'Agent 完成质控与分析' : event.event_type === 'EVIDENCE_QUERY' ? '循证 Agent 完成来源检索' : '医生提交复核结论'}</strong><p>{event.actor} · {event.to_status ? statusLabels[event.to_status] || event.to_status : '任务创建'}</p></div><time>{formatDate(event.created_at)}</time></article>)}</section>
        </>}
      </section>
    </section>
    <footer className="review-footer">本工作台为科研原型。模型结果不构成临床诊断、分期、处方或治疗建议。</footer>
  </main>;
}
