'use client';

import BackToAgent from '../back-to-agent';
import { useEffect, useMemo, useRef, useState } from 'react';
import ImageViewer from '../components/image-viewer';
import AnalysisQueuePanel, { activeJobStates, useAnalysisQueue } from '../components/analysis-queue';
import { apiBaseUrl, responseMessage } from '../auth-client';

const samples = [
  { key: 'adeno', label: '腺癌示例', image: '/ct-adeno.png' },
  { key: 'large', label: '大细胞癌示例', image: '/ct-large.png' },
  { key: 'normal', label: '正常肺部示例', image: '/ct-normal.png' },
  { key: 'squamous', label: '鳞癌示例', image: '/ct-squamous.png' },
] as const;

const classLabels: Record<string, string> = {
  adenocarcinoma: '腺癌',
  large_cell_carcinoma: '大细胞癌',
  normal: '正常肺部',
  squamous_cell_carcinoma: '鳞状细胞癌',
};

type AnalysisResult = {
  task_id: string;
  status: string;
  input: { file_name: string; image_size: [number, number] };
  model: { name: string; version: string; folds: number; inference_ms: number; architecture_matches_original_plan?: boolean; exact_original_weights?: boolean };
  prediction: { decision: 'RESEARCH_RANKING' | 'INDETERMINATE'; top_class: string; top_class_cn: string; probabilities: Record<string, number> };
  reliability: { level: string; fold_agreement: string; warnings: string[]; thresholds?: Record<string, number | string | boolean> };
  applicability?: { status: string; within_training_domain_verified: boolean; clinical_candidate_allowed: boolean; pathology_conclusion_allowed: boolean; case_aggregation_allowed: boolean; reasons: string[] };
  quality_control: { status: string; warnings: string[] };
  priority: { level: string; label_cn: string; reasons: string[] };
  attention: { available: boolean; method: string };
  disclaimer: string;
};

type Explanation = {
  answer: string;
  support_level: string;
  uncertainty: string[];
  next_steps: string[];
  evidence: { citation_id: string; title: string; excerpt: string; verified?: boolean }[];
  conversation_id: string;
};

type SeriesResult = {
  series_id: string;
  case_name: string;
  created_at: string;
  status: string;
  summary: { uploaded_count: number; analyzed_count: number; failed_count: number; quality_warning_count: number; quality_warning_ratio?: number };
  prediction: {
    decision: 'CANDIDATE' | 'INDETERMINATE';
    top_class: string;
    top_class_cn: string;
    top_probability: number;
    probabilities: Record<string, number>;
    slice_agreement: number;
  };
  reliability: { level: string; top_two_margin: number; warnings: string[] };
  applicability?: {
    case_aggregation_validated: boolean;
    clinical_candidate_allowed: boolean;
    lesion_roi_available: boolean;
    dicom_train_serving_equivalence_verified: boolean;
    interpretation: string;
  };
  quality_gate?: {
    status: 'PASS' | 'BLOCKED';
    reasons: string[];
    metrics: { analyzed_slice_count: number; quality_warning_ratio: number; top_probability: number; top_two_margin: number; slice_agreement: number };
    thresholds: Record<string, number>;
    rule_version: string;
  };
  representative_slice: { task_id: string; file_name: string };
  items: AnalysisResult[];
  failures: { file_name: string; status_code: number; detail: string }[];
  input_mode?: 'IMAGE' | 'DICOM';
  dicom?: {
    input_file_count: number;
    readable_slice_count: number;
    analyzed_slice_count: number;
    subsampled: boolean;
    maximum_analysis_slices: number;
    window: { name: string; center_hu: number; width_hu: number };
    lung_selection?: {
      status: 'APPLIED' | 'FALLBACK_ALL';
      method: string;
      scope: string;
      input_slice_count: number;
      eligible_slice_count: number;
      excluded_edge_slice_count: number;
    };
    privacy: {
      direct_identifier_fields_detected: string[];
      identifier_values_persisted: boolean;
      original_dicom_persisted: boolean;
      burned_in_annotation: string[];
      pixel_privacy_review_required: boolean;
    };
  };
  disclaimer: string;
};

export default function CtAnalysisWorkspace() {
  const [sampleIndex, setSampleIndex] = useState(0);
  const [uploadMode, setUploadMode] = useState<'image' | 'dicom'>('image');
  const [dicomAcknowledged, setDicomAcknowledged] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [caseName, setCaseName] = useState('');
  const [previewUrl, setPreviewUrl] = useState('');
  const [results, setResults] = useState<AnalysisResult[]>([]);
  const [seriesResult, setSeriesResult] = useState<SeriesResult | null>(null);
  const [seriesHistory, setSeriesHistory] = useState<SeriesResult[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [activeResult, setActiveResult] = useState(0);
  const [running, setRunning] = useState(false);
  const lastSeries = useRef('');
  const selectedJob = useRef('');
  const selectionRevision = useRef(0);
  const [error, setError] = useState('');
  const [explanations, setExplanations] = useState<Record<string, Explanation>>({});
  const [explanationErrors, setExplanationErrors] = useState<Record<string, string>>({});
  const [explainingTask, setExplainingTask] = useState('');

  useEffect(() => {
    let active = true;
    void fetch(`${apiBaseUrl}/api/series?limit=20`, { credentials: 'include' }).then(async (response) => {
      if (response.status === 401) { window.location.replace(`/auth?returnTo=${encodeURIComponent('/analysis')}`); return; }
      if (!response.ok) throw new Error(await responseMessage(response, '无法读取病例历史'));
      const payload = await response.json() as { items: SeriesResult[] };
      if (active) setSeriesHistory(payload.items);
    }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : '无法读取病例历史'); })
      .finally(() => { if (active) setHistoryLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const result = results[activeResult] || null;
  const probabilities = useMemo(() => result ? Object.entries(result.prediction.probabilities).sort((a, b) => b[1] - a[1]) : [], [result]);
  const seriesProbabilities = useMemo(() => seriesResult ? Object.entries(seriesResult.prediction.probabilities).sort((a, b) => b[1] - a[1]) : [], [seriesResult]);
  const seriesExplanation = seriesResult ? explanations[seriesResult.representative_slice.task_id] : undefined;
  const preview = result
    ? `${apiBaseUrl}/api/tasks/${encodeURIComponent(result.task_id)}/image`
    : previewUrl || (uploadMode === 'image' ? samples[sampleIndex].image : '');

  const selectFiles = (list: FileList | null, mode: 'image' | 'dicom') => {
    const selected = list ? Array.from(list) : [];
    if (!selected.length) return;
    selectionRevision.current += 1; lastSeries.current = ''; queue.clear();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setUploadMode(mode);
    setFiles(selected);
    setPreviewUrl(mode === 'image' ? URL.createObjectURL(selected[0]) : '');
    setResults([]); setSeriesResult(null); setActiveResult(0);  setError('');
  };

  const changeUploadMode = (mode: 'image' | 'dicom') => {
    selectionRevision.current += 1; lastSeries.current = ''; queue.clear();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setUploadMode(mode); setFiles([]); setPreviewUrl(''); setResults([]); setSeriesResult(null);
    setActiveResult(0);  setError(''); setDicomAcknowledged(false);

  };

  const selectSample = (index: number) => {
    selectionRevision.current += 1; lastSeries.current = ''; queue.clear();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setSampleIndex(index); setUploadMode('image'); setFiles([]); setCaseName(''); setPreviewUrl(''); setResults([]); setSeriesResult(null); setActiveResult(0);  setError(''); setDicomAcknowledged(false);
  };

  const openStoredSeries = async (seriesId: string, keepSlice = false) => {
    const revision = ++selectionRevision.current;
    if (!keepSlice) { queue.clear(); lastSeries.current = ''; }
    setHistoryLoading(true); setError('');
    try {
      const response = await fetch(`${apiBaseUrl}/api/series/${encodeURIComponent(seriesId)}`, { credentials: 'include' });
      if (response.status === 401) { window.location.replace(`/auth?returnTo=${encodeURIComponent('/analysis')}`); return; }
      if (!response.ok) throw new Error(await responseMessage(response, '病例记录读取失败'));
      const series = await response.json() as SeriesResult;
      if (revision !== selectionRevision.current) return;
      const representativeIndex = series.items.findIndex((item) => item.task_id === series.representative_slice.task_id);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setFiles([]); setPreviewUrl(''); setCaseName(series.case_name); setSeriesResult(series); setResults(series.items);
      setSeriesHistory(current => [series, ...current.filter(item => item.series_id !== seriesId)].slice(0, 20));
      setUploadMode(series.input_mode === 'DICOM' ? 'dicom' : 'image');
      setActiveResult(current => keepSlice ? Math.max(0, Math.min(current, series.items.length - 1)) : Math.max(0, representativeIndex));
      const evidenceResponse = await fetch(`${apiBaseUrl}/api/tasks/${encodeURIComponent(series.representative_slice.task_id)}/evidence/history`, { credentials: 'include' });
      if (evidenceResponse.ok) {
        const evidencePayload = await evidenceResponse.json() as { items: Explanation[] };
        if (evidencePayload.items[0]) setExplanations((current) => ({ ...current, [series.representative_slice.task_id]: evidencePayload.items[0] }));
      }
    } catch (reason) { if (revision === selectionRevision.current) { lastSeries.current = ''; setError(reason instanceof Error ? reason.message : '病例记录读取失败'); } }
    finally { if (revision === selectionRevision.current) setHistoryLoading(false); }
  };

  const queue = useAnalysisQueue<AnalysisResult>(job => {
    if (selectedJob.current !== job.job_id) {
      selectedJob.current = job.job_id; selectionRevision.current += 1;
      lastSeries.current = ''; setSeriesResult(null); setActiveResult(0);
    }
    setRunning(activeJobStates.has(job.state));
    setResults(job.results);
    setActiveResult(current => Math.max(0, Math.min(current, job.results.length - 1)));
    if (job.series_id && lastSeries.current !== job.series_id) {
      lastSeries.current = job.series_id;
      void openStoredSeries(job.series_id, true);
    } else if (!job.series_id) { setSeriesResult(null); lastSeries.current = ''; }
  });
  const runAnalysis = async () => {
    if (running) return;
    selectionRevision.current += 1; lastSeries.current = ''; queue.clear();
    setRunning(true); setError(''); setResults([]); setSeriesResult(null); setActiveResult(0);
    try {
      if (uploadMode === 'dicom' && (!files.length || !dicomAcknowledged)) throw new Error('请选择DICOM文件并确认数据授权与像素隐私复核要求');
      const form = new FormData();
      if (files.length) files.forEach(file => form.append('files', file));
      else {
        const sample = await fetch(samples[sampleIndex].image);
        if (!sample.ok) throw new Error('示例影像无法读取');
        form.append('files', await sample.blob(), `${samples[sampleIndex].key}.png`);
      }
      form.append('mode', uploadMode);
      form.append('case_name', caseName.trim() || (files.length ? '影像分析任务' : samples[sampleIndex].label));
      form.append('privacy_acknowledged', String(dicomAcknowledged));
      const response = await fetch(`${apiBaseUrl}/api/analysis-jobs`, { method: 'POST', body: form, credentials: 'include' });
      if (!response.ok) throw new Error(await responseMessage(response, '任务提交失败，请检查本地服务'));
      queue.accept(await response.json());
    } catch (reason) { setError(reason instanceof Error ? reason.message : '任务提交失败'); setRunning(false); }
  };

  const generateExplanation = async (item: AnalysisResult, seriesMode = false) => {
    if (explainingTask) return;
    setExplainingTask(item.task_id);
    setExplanationErrors((current) => ({ ...current, [item.task_id]: '' }));
    try {
      const response = await fetch(`${apiBaseUrl}/api/tasks/${encodeURIComponent(item.task_id)}/evidence/query`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: seriesMode
            ? '请基于当前病例多切片的内部聚合排序、代表切片、切片一致率、五折一致性、质控结果和本地资料库，解释模型输出与阻断原因；说明冲突切片、易混淆类别、不确定性和需要核验的影像特征。病例级聚合尚未验证，不得把内部最高排序称为病例候选、组织学判断或诊断。不要给出分期或治疗建议。'
            : '请基于当前CT结构化闭集排序、五折一致性、质控结果和本地资料库，解释模型内部输出及局限；说明易混淆类别、不确定性和需要进一步核验的影像特征。不得把类别排序称为病理诊断、患癌概率或细胞形态识别。不要给出分期或治疗建议。',
          include_in_report: true,
        }),
      });
      if (response.status === 401) { window.location.replace(`/auth?returnTo=${encodeURIComponent('/analysis')}`); return; }
      if (!response.ok) throw new Error(await responseMessage(response, 'AI解释生成失败'));
      const explanation = await response.json() as Explanation;
      setExplanations((current) => ({ ...current, [item.task_id]: explanation }));
    } catch (reason) {
      setExplanationErrors((current) => ({ ...current, [item.task_id]: reason instanceof Error ? reason.message : 'AI解释生成失败' }));
    } finally { setExplainingTask(''); }
  };

  return <main className="analysis-shell">
    <header className="rag-topbar analysis-topbar">
      <a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>CT ANALYSIS WORKSPACE</small></span></a>
      <nav><BackToAgent /></nav>
    </header>

    <section className="analysis-heading"><div><span>LOCAL FIVE-FOLD RESEARCH INFERENCE</span><h1>肺部CT影像分析</h1><p>当前模型延续最初的五折ResNet18四分类架构，但权重为审计后重新训练的研究版本。输出只表示闭集内部排序，不是癌细胞形态识别、病理诊断或患癌概率。</p></div><div><i /> 研究模型已连接<strong>5 / 5 folds</strong></div></section>

    <AnalysisQueuePanel queue={queue} />
    <section className="analysis-workspace">
      <aside className="analysis-intake">
        <div className="analysis-section-title"><span>01 · IMAGE INTAKE</span><h2>选择待分析影像</h2></div>
        <div className="analysis-upload-tabs"><button className={uploadMode === 'image' ? 'active' : ''} disabled={running} onClick={() => changeUploadMode('image')}>普通图片</button><button className={uploadMode === 'dicom' ? 'active' : ''} disabled={running} onClick={() => changeUploadMode('dicom')}>DICOM序列</button></div>
        {uploadMode === 'image' ? <label className="analysis-upload"><input aria-label="上传肺部CT影像" disabled={running} type="file" multiple accept=".png,.jpg,.jpeg,.bmp,.tif,.tiff,image/png,image/jpeg,image/bmp,image/tiff" onChange={(event) => selectFiles(event.target.files, 'image')} /><i>＋</i><strong>上传或批量选择CT图片</strong><small>PNG / JPG / BMP / TIFF · 单张20MB以内</small></label> : <label className="analysis-upload analysis-upload-dicom"><input aria-label="上传DICOM序列" disabled={running} type="file" multiple accept=".dcm,application/dicom" onChange={(event) => selectFiles(event.target.files, 'dicom')} /><i>DCM</i><strong>选择同一个CT序列</strong><small>单帧CT DICOM · 最多512个 · 总计256MB</small></label>}
        {(files.length > 1 || uploadMode === 'dicom') && <label className="analysis-case-name"><span>病例名称（请勿填写患者身份信息）</span><input value={caseName} maxLength={120} placeholder="例如：匿名病例 001" onChange={(event) => setCaseName(event.target.value)} /></label>}
        {!!files.length && <div className="analysis-file-list"><span>已选择 {files.length} {uploadMode === 'dicom' ? '个文件' : '张'}</span>{files.slice(0, 12).map((file, index) => <p key={`${file.name}-${index}`}><b>{String(index + 1).padStart(2, '0')}</b><span>{uploadMode === 'dicom' ? `DICOM文件 ${String(index + 1).padStart(4, '0')}` : file.name}</span><small>{(file.size / 1024 / 1024).toFixed(2)} MB</small></p>)}{files.length > 12 && <small className="analysis-file-more">其余 {files.length - 12} 个文件已选择</small>}</div>}
        {uploadMode === 'dicom' && <label className="analysis-dicom-consent"><input type="checkbox" checked={dicomAcknowledged} onChange={(event) => setDicomAcknowledged(event.target.checked)} /><span>我确认数据已获授权并仅在本机处理；系统不保存原始DICOM或身份字段值，但像素区域仍需人工隐私复核。</span></label>}
        {uploadMode === 'image' && <div className="analysis-samples"><span>或使用内置示例</span>{samples.map((sample, index) => <button key={sample.key} className={!files.length && sampleIndex === index ? 'active' : ''} disabled={running} onClick={() => selectSample(index)}><i>{String(index + 1).padStart(2, '0')}</i><span>{sample.label}</span></button>)}</div>}
        <button className="analysis-run" disabled={running} onClick={() => void runAnalysis()}>{running ? `分析中 ${queue.job?.completed || 0}/${queue.job?.total || files.length || 1}` : '运行本地五折分析 →'}</button>
        {error && <div className="analysis-error">{error}</div>}
        <section className="analysis-history">
          <header><div><span>CASE HISTORY</span><h3>病例分析记录</h3></div><b>{seriesHistory.length}</b></header>
          {historyLoading && !seriesHistory.length && <p>正在读取病例记录…</p>}
          {!historyLoading && !seriesHistory.length && <p>完成一次多切片分析后，病例会显示在这里。</p>}
          <div>{seriesHistory.map((series) => <article key={series.series_id} className={seriesResult?.series_id === series.series_id ? 'active' : ''}>
            <button type="button" disabled={running} onClick={() => void openStoredSeries(series.series_id)}><strong>{series.case_name}</strong><span>病例级结论已阻断 · 内部最高排序 {series.prediction.top_class_cn}</span><small>{series.summary.analyzed_count}张 · {new Date(series.created_at).toLocaleString('zh-CN')}</small></button>
            <a href={`${apiBaseUrl}/api/series/${encodeURIComponent(series.series_id)}/report`} title="下载病例报告">↓</a>
          </article>)}</div>
        </section>
      </aside>

      <section className="analysis-viewer">
        {preview ? <ImageViewer src={preview} attentionSrc={result?.attention.available ? `${apiBaseUrl}/api/tasks/${encodeURIComponent(result.task_id)}/attention` : undefined} taskId={result?.task_id} title={result?.input.file_name || files[0]?.name || samples[sampleIndex].label} sliceIndex={activeResult} sliceCount={Math.max(results.length, 1)} onSliceChange={setActiveResult} /> : <div className="analysis-dicom-placeholder"><strong>DICOM 等待本地解析</strong><p>完成肺窗转换后可浏览已分析切片；原始DICOM不落库。</p></div>}
        <footer><span>影像由本地服务处理 · DICOM 显示派生切片</span><span>不上传至大模型服务商</span></footer>
      </section>

      <aside className="analysis-result">
        <div className="analysis-section-title"><span>02 · MODEL OUTPUT</span><h2>{seriesResult ? '病例综合结果' : result ? '分析结果' : '等待运行'}</h2></div>
        {!result && <div className="analysis-result-empty"><i>CT</i><strong>尚未生成结果</strong><p>选择影像并运行分析后，此处显示闭集内部排序、折间一致性、质控和适用性门控。</p></div>}
        {result && <>
          {seriesResult && <section className={`analysis-series ${seriesResult.prediction.decision === 'INDETERMINATE' ? 'indeterminate' : ''}`}>
            <header><span>UNVALIDATED CASE AGGREGATION</span><b>病例级结论已阻断</b></header>
            <h3>{seriesResult.case_name}</h3>
            <div className="analysis-series-primary"><span>内部最高排序：{seriesResult.prediction.top_class_cn}</span><strong>{(seriesResult.prediction.top_probability * 100).toFixed(1)}%</strong></div>
            <div className="analysis-series-bars">{seriesProbabilities.map(([key, value]) => <div key={key}><span>{classLabels[key] || key}<b>{(value * 100).toFixed(1)}%</b></span><i><em style={{ width: `${value * 100}%` }} /></i></div>)}</div>
            <dl><div><dt>有效切片</dt><dd>{seriesResult.summary.analyzed_count} / {seriesResult.summary.uploaded_count}</dd></div><div><dt>切片一致率</dt><dd>{(seriesResult.prediction.slice_agreement * 100).toFixed(0)}%</dd></div><div><dt>代表切片</dt><dd title={seriesResult.representative_slice.file_name}>{seriesResult.representative_slice.file_name}</dd></div></dl>
            {seriesResult.dicom && <div className="analysis-dicom-summary"><strong>DICOM本地导入</strong><span>{seriesResult.dicom.readable_slice_count}层可读 · 肺野区间{seriesResult.dicom.lung_selection?.eligible_slice_count ?? seriesResult.dicom.readable_slice_count}层 · 排除边缘低覆盖{seriesResult.dicom.lung_selection?.excluded_edge_slice_count ?? 0}层 · {seriesResult.dicom.analyzed_slice_count}层进入模型</span><span>肺窗 C{seriesResult.dicom.window.center_hu}/W{seriesResult.dicom.window.width_hu}</span><small>肺野筛选只是覆盖度质控，不是肺分割或病灶定位；原始DICOM及身份字段值未保存，像素隐私仍需人工复核。</small></div>}
            {seriesResult.quality_gate && <div className={`analysis-quality-gate ${seriesResult.quality_gate.status === 'BLOCKED' ? 'blocked' : ''}`}><strong>{seriesResult.quality_gate.status === 'PASS' ? '仅工程门槛通过' : '适用性门控已阻断病例级结论'}</strong><span>{seriesResult.quality_gate.reasons.length ? seriesResult.quality_gate.reasons.join('；') : '病例级工程阈值通过，但不代表临床验证'}</span><small>规则 {seriesResult.quality_gate.rule_version} · 质控异常比例 {((seriesResult.summary.quality_warning_ratio || 0) * 100).toFixed(1)}%</small></div>}
            {!!seriesResult.reliability.warnings.length && <p>{seriesResult.reliability.warnings.join('；')}</p>}
            {!seriesExplanation && <button className="analysis-explain" disabled={explainingTask === seriesResult.representative_slice.task_id} onClick={() => { const representative = results.find((item) => item.task_id === seriesResult.representative_slice.task_id); if (representative) void generateExplanation(representative, true); }}>{explainingTask === seriesResult.representative_slice.task_id ? '正在生成模型说明…' : '生成聚合输出与局限说明'}</button>}
            {seriesExplanation && <section className="analysis-explanation"><header><span>CASE RATIONALE</span><b>{seriesExplanation.support_level}</b></header><p>{seriesExplanation.answer}</p>{!!seriesExplanation.evidence?.length && <div>{seriesExplanation.evidence.map((citation) => <span key={citation.citation_id} title={citation.excerpt}>{citation.citation_id} · {citation.title}{citation.verified !== false ? ' ✓' : ''}</span>)}</div>}{!!seriesExplanation.uncertainty?.length && <small>不确定性：{seriesExplanation.uncertainty.join('；')}</small>}</section>}
          </section>}
          {results.length > 1 && <select aria-label="切换分析结果" value={activeResult} onChange={(event) => { setActiveResult(Number(event.target.value));  }}>{results.map((item, index) => <option key={item.task_id} value={index}>{item.input.file_name}</option>)}</select>}
          {seriesResult && <div className="analysis-slice-label">当前切片结果</div>}
          <div className="analysis-primary"><span>内部最高排序（非诊断）</span><strong>{result.prediction.top_class_cn}</strong><b>{((result.prediction.probabilities[result.prediction.top_class] || 0) * 100).toFixed(1)}%</b><small>{result.prediction.decision === 'RESEARCH_RANKING' ? '达到内部研究门槛' : '已触发拒判'} · {result.task_id}</small></div>
          <div className="analysis-probabilities">{probabilities.map(([key, value]) => <div key={key}><span>{classLabels[key] || key}<b>{(value * 100).toFixed(1)}%</b></span><i><em style={{ width: `${value * 100}%` }} /></i></div>)}</div>
          <div className="analysis-result-meta"><span><small>五折一致性</small><b>{result.reliability.fold_agreement}</b></span><span><small>影像质控</small><b>{result.quality_control.status === 'PASS' ? '通过' : '有提示'}</b></span><span><small>复核队列</small><b>{result.priority.label_cn}</b></span><span><small>Grad-CAM</small><b>{result.attention.available ? '已生成' : '不可用'}</b></span></div>
          <div className="analysis-caution"><b>AI提示</b><p>{result.reliability.warnings.length ? result.reliability.warnings.join('；') : '五折输出稳定，但仍需结合完整影像、临床信息和病理结果复核。'}</p></div>
          {!seriesResult && !explanations[result.task_id] && <button className="analysis-explain" disabled={explainingTask === result.task_id} onClick={() => void generateExplanation(result)}>{explainingTask === result.task_id ? '正在检索资料并生成说明…' : '生成模型输出与局限说明'}</button>}
          {explanationErrors[result.task_id] && <div className="analysis-explanation-error">{explanationErrors[result.task_id]}<a href={`/agent?task=${result.task_id}`}>前往Agent配置或继续提问</a></div>}
          {!seriesResult && explanations[result.task_id] && <section className="analysis-explanation"><header><span>AI JUDGEMENT RATIONALE</span><b>{explanations[result.task_id].support_level}</b></header><p>{explanations[result.task_id].answer}</p>{!!explanations[result.task_id].evidence?.length && <div>{explanations[result.task_id].evidence.map((citation) => <span key={citation.citation_id} title={citation.excerpt}>{citation.citation_id} · {citation.title}{citation.verified !== false ? ' ✓' : ''}</span>)}</div>}{!!explanations[result.task_id].uncertainty?.length && <small>不确定性：{explanations[result.task_id].uncertainty.join('；')}</small>}</section>}
          <div className={`analysis-result-actions ${seriesResult ? 'series-actions' : ''}`}><a href={`/case?task=${result.task_id}`}>打开病例工作区</a><a href={`/agent?task=${result.task_id}`}>进入关联CT对话</a>{seriesResult && <a href={`${apiBaseUrl}/api/series/${encodeURIComponent(seriesResult.series_id)}/report`}>下载病例报告</a>}</div>
        </>}
      </aside>
    </section>
    <p className="analysis-disclaimer">DICOM支持仅为本地导入与工程观察，尚未验证与训练图片的输入等价性，也没有肿瘤ROI定位；所有输出均为弱标签研究排序，不构成病例级候选、临床诊断或病理细胞类型结论。</p>
  </main>;
}
