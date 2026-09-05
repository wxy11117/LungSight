'use client';

import BackToAgent from '../back-to-agent';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { apiFetch } from '../auth-client';

type DatasetSummary = {
  dataset_version: string;
  description: string;
  total_cases: number;
  categories: { key: string; label: string; count: number }[];
};

type RunSummary = {
  run_id: string;
  dataset_version: string;
  completed_at: string;
  total_cases: number;
  passed_cases: number;
  overall_score: number;
  status_accuracy: number;
  citation_accuracy: number;
  content_accuracy: number;
  safety_accuracy: number;
  unsupported_accuracy: number;
};

type CaseResult = {
  case_id: string;
  category: string;
  category_label: string;
  question: string;
  expected_support: string;
  actual_support: string;
  passed: boolean;
  checks: { status: boolean; content: boolean; citation: boolean; no_unsupported_evidence: boolean };
  matched_content_groups: number;
  total_content_groups: number;
  evidence_count: number;
  top_citations: { citation_id: string; title: string; locator: string; page_number: number | null }[];
  answer_preview: string;
};

type RunDetail = RunSummary & {
  started_at: string;
  category_metrics: { key: string; label: string; total: number; passed: number; score: number }[];
  results: CaseResult[];
};

type RagDataset = { dataset_version: string; description: string; total_cases: number; categories: { key: string; label: string; count: number }[] };
type RagRun = { run_id: string; dataset_version: string; total_cases: number; passed_cases: number; faithfulness_score: number; citation_score: number; refusal_score: number; privacy_score: number; unsupported_score: number; overall_score: number; completed_at: string; provider: string };

const supportLabels: Record<string, string> = {
  SUPPORTED: '证据支持',
  PARTIALLY_SUPPORTED: '部分支持',
  INSUFFICIENT: '证据不足',
  REFUSED: '安全拒答',
};

const formatDate = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
}).format(new Date(value));

export default function EvaluationPage() {
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [category, setCategory] = useState('ALL');
  const [onlyFailed, setOnlyFailed] = useState(false);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [ragDataset, setRagDataset] = useState<RagDataset | null>(null);
  const [ragRun, setRagRun] = useState<RagRun | null>(null);
  const [ragRunning, setRagRunning] = useState(false);

  const loadRun = useCallback(async (runId: string) => {
    const response = await apiFetch(`/api/evaluation/runs/${runId}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('无法读取评测运行明细');
    setSelectedRun(await response.json());
  }, []);

  const loadDashboard = useCallback(async () => {
    setError('');
    try {
      const [datasetResponse, runsResponse, ragDatasetResponse, ragRunsResponse] = await Promise.all([
        apiFetch('/api/evaluation/dataset', { cache: 'no-store' }),
        apiFetch('/api/evaluation/runs?limit=8', { cache: 'no-store' }),
        apiFetch('/api/agent/evaluation/dataset', { cache: 'no-store' }),
        apiFetch('/api/agent/evaluation/runs?limit=1', { cache: 'no-store' }),
      ]);
      if (!datasetResponse.ok || !runsResponse.ok) throw new Error('Agent 评测服务暂不可用');
      const datasetPayload: DatasetSummary = await datasetResponse.json();
      const runsPayload: { items: RunSummary[] } = await runsResponse.json();
      setDataset(datasetPayload);
      setRuns(runsPayload.items);
      if (ragDatasetResponse.ok) setRagDataset(await ragDatasetResponse.json());
      if (ragRunsResponse.ok) {
        const ragRunsPayload: { items: RagRun[] } = await ragRunsResponse.json();
        setRagRun(ragRunsPayload.items[0] || null);
      }
      if (runsPayload.items[0]) await loadRun(runsPayload.items[0].run_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Agent 评测服务暂不可用');
    } finally {
      setLoading(false);
    }
  }, [loadRun]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadDashboard(); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadDashboard]);

  const runEvaluation = async () => {
    setRunning(true);
    setError('');
    try {
      const response = await apiFetch('/api/evaluation/run', { method: 'POST' });
      if (!response.ok) throw new Error('本次评测执行失败');
      const result: RunDetail = await response.json();
      setSelectedRun(result);
      setRuns((current) => [result, ...current.filter((item) => item.run_id !== result.run_id)].slice(0, 8));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '本次评测执行失败');
    } finally {
      setRunning(false);
    }
  };

  const runRagEvaluation = async () => {
    setRagRunning(true); setError('');
    try {
      const response = await apiFetch('/api/agent/evaluation/run', { method: 'POST' });
      if (!response.ok) throw new Error('RAG专项评测执行失败');
      setRagRun(await response.json());
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'RAG专项评测执行失败'); }
    finally { setRagRunning(false); }
  };

  const visibleCases = useMemo(() => {
    if (!selectedRun) return [];
    return selectedRun.results.filter((item) =>
      (category === 'ALL' || item.category === category) && (!onlyFailed || !item.passed));
  }, [selectedRun, category, onlyFailed]);

  return <main className="evaluation-shell">
    <header className="evaluation-nav">
      <a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>AGENT EVALUATION LAB</small></span></a>
      <div><BackToAgent /><span className="local-status"><i /> 受保护评测环境</span></div>
    </header>

    <section className="evaluation-hero">
      <div><span>REGRESSION · TRACEABILITY · SAFETY</span><h1>Agent 可靠性评测台</h1><p>用固定题集持续检查事实回答、证据定位、未知问题拒答和医疗安全边界。评测查询不会写入病例记录。</p></div>
      <button onClick={()=>void runEvaluation()} disabled={running}>{running ? '正在运行 38 项检查…' : '运行完整评测 →'}</button>
    </section>

    {error && <div className="evaluation-error">{error}</div>}
    {loading && <div className="evaluation-loading">正在读取本地评测记录…</div>}

    {!loading && dataset && <>
      <section className="dataset-strip">
        <div><span>DATASET</span><strong>{dataset.dataset_version}</strong><small>{dataset.description}</small></div>
        <div><strong>{dataset.total_cases}</strong><span>固定测试用例</span></div>
        <div><strong>{dataset.categories.length}</strong><span>能力维度</span></div>
        <div><strong>0</strong><span>病例记录污染</span></div>
      </section>

      {selectedRun ? <>
        <section className="evaluation-overview">
          <article className="score-card">
            <div className="score-ring" style={{'--score': `${selectedRun.overall_score * 3.6}deg`} as CSSProperties}><span><strong>{selectedRun.overall_score.toFixed(1)}</strong><small>总分 / 100</small></span></div>
            <div><span>LATEST EVALUATION</span><h2>{selectedRun.passed_cases} / {selectedRun.total_cases} 项通过</h2><p>{formatDate(selectedRun.completed_at)} · {selectedRun.run_id}</p></div>
          </article>
          <div className="metric-grid">
            {[
              ['状态判断', selectedRun.status_accuracy, '支持 / 不足 / 拒答'],
              ['来源定位', selectedRun.citation_accuracy, '文件与证据匹配'],
              ['内容覆盖', selectedRun.content_accuracy, '关键事实命中'],
              ['安全拒答', selectedRun.safety_accuracy, '患者级诊疗边界'],
              ['无证据拒答', selectedRun.unsupported_accuracy, '未知事实不臆测'],
            ].map(([label,value,note])=><article key={String(label)}><span>{label}</span><strong>{Number(value).toFixed(1)}%</strong><i><em style={{width:`${value}%`}} /></i><small>{note}</small></article>)}
          </div>
        </section>

        <section className="category-score-grid">
          {selectedRun.category_metrics.map((item)=><article key={item.key}><div><span>{item.label}</span><small>{item.passed}/{item.total} 通过</small></div><strong>{item.score.toFixed(0)}%</strong></article>)}
        </section>

        <section className="evaluation-results">
          <div className="evaluation-results-head">
            <div><span>CASE LEVEL EVIDENCE</span><h2>逐项验收结果</h2></div>
            <div className="evaluation-filters">
              <select aria-label="能力维度" value={category} onChange={(event)=>setCategory(event.target.value)}><option value="ALL">全部能力维度</option>{dataset.categories.map((item)=><option key={item.key} value={item.key}>{item.label} · {item.count}</option>)}</select>
              <label><input type="checkbox" checked={onlyFailed} onChange={(event)=>setOnlyFailed(event.target.checked)} /> 只看未通过</label>
            </div>
          </div>
          <div className="evaluation-case-list">
            {!visibleCases.length && <div className="all-passed">✓ 当前筛选范围内没有未通过项</div>}
            {visibleCases.map((item)=><details key={item.case_id} className={item.passed ? 'evaluation-case passed' : 'evaluation-case failed'}>
              <summary><span>{item.case_id}</span><div><strong>{item.question}</strong><small>{item.category_label} · 实际状态：{supportLabels[item.actual_support] ?? item.actual_support}</small></div><i>{item.passed ? '通过' : '检查'}</i></summary>
              <div className="evaluation-case-body">
                <div className="check-row">
                  {Object.entries({状态:item.checks.status,内容:item.checks.content,引用:item.checks.citation,无越界证据:item.checks.no_unsupported_evidence}).map(([label,ok])=><span className={ok?'ok':'bad'} key={label}>{ok?'✓':'!'} {label}</span>)}
                  <span>{item.matched_content_groups}/{item.total_content_groups || 0} 内容要点</span><span>{item.evidence_count} 条证据</span>
                </div>
                <p>{item.answer_preview}</p>
                {!!item.top_citations.length && <div className="case-citations">{item.top_citations.map((citation)=><span key={`${item.case_id}-${citation.citation_id}`}><b>{citation.citation_id}</b>{citation.title}<small>{citation.page_number ? `第 ${citation.page_number} 页` : citation.locator}</small></span>)}</div>}
              </div>
            </details>)}
          </div>
        </section>
      </> : <section className="no-evaluation"><h2>尚未生成评测基线</h2><p>运行完整评测后，将显示能力得分和逐项证据。</p></section>}

      {!!runs.length && <section className="evaluation-history"><div><span>RUN HISTORY</span><h2>历史运行</h2></div><div>{runs.map((run)=><button key={run.run_id} className={selectedRun?.run_id===run.run_id?'active':''} onClick={()=>void loadRun(run.run_id)}><span>{formatDate(run.completed_at)}</span><strong>{run.overall_score.toFixed(1)}</strong><small>{run.passed_cases}/{run.total_cases} 通过</small></button>)}</div></section>}

      {ragDataset && <section className="rag-evaluation-card">
        <div className="rag-eval-title"><div><span>MEDICAL RAG · MOCK OPENAI</span><h2>RAG闭环专项验收</h2><p>{ragDataset.description}</p></div><button onClick={() => void runRagEvaluation()} disabled={ragRunning}>{ragRunning ? '正在执行离线闭环…' : '运行RAG专项评测 →'}</button></div>
        <div className="rag-eval-metrics">
          <article><span>用例</span><strong>{ragRun ? `${ragRun.passed_cases}/${ragRun.total_cases}` : ragDataset.total_cases}</strong><small>{ragDataset.dataset_version}</small></article>
          {[['答案忠实性',ragRun?.faithfulness_score],['引用正确性',ragRun?.citation_score],['安全拒答',ragRun?.refusal_score],['隐私脱敏',ragRun?.privacy_score],['证据不足',ragRun?.unsupported_score]].map(([label,value])=><article key={String(label)}><span>{label}</span><strong>{value === undefined ? '待运行' : `${Number(value).toFixed(1)}%`}</strong><small>Mock Provider · 零真实API调用</small></article>)}
        </div>
        {ragRun && <footer><span>最近运行：{formatDate(ragRun.completed_at)}</span><span>{ragRun.run_id}</span><strong>综合 {ragRun.overall_score.toFixed(1)}%</strong></footer>}
      </section>}
    </>}

    <footer className="evaluation-footer">评测结果仅反映固定本地题集上的回归表现，不等同于临床有效性或外部泛化证明。</footer>
  </main>;
}
