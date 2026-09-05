'use client';

import BackToAgent from '../back-to-agent';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiBaseUrl, apiFetch, responseMessage } from '../auth-client';
import './library-research.css';

type Metadata = {
  category?: string; classes?: string[]; original_title?: string; pmid?: string; doi?: string;
  checked_at?: string; verification?: string; evidence_level?: string; review_status?: string;
  limitations?: string; content_kind?: string; review_note?: string; retracted?: boolean; preprint?: boolean;
};
type Source = {
  source_id: string; title: string; source_type: string; version: string; publication_date: string | null;
  authority: string; scope: string; locator: string; chunk_count: number;
  retrieval_enabled: boolean; metadata: Metadata; can_review: boolean;
};
type Payload = { items: Source[]; counts: { sources: number; chunks: number; active_sources: number }; scope: string };
type Paper = {
  pmid: string; title: string; doi: string; authors: string; journal: string; publication_date: string;
  abstract_preview: string; url: string; open_access: boolean; retracted: boolean; preprint: boolean;
};
type SearchResult = { items: Paper[]; total: number; checked_at: string; topic: string };
const categoryLabels: Record<string, string> = {
  guideline: '治疗与筛查指南', pathology: '细胞与病理形态', ct_features: 'CT影像征象',
  prediction: 'CT分型预测研究', methods: '研究方法与标准', dataset: '影像数据集索引',
  literature: '在线导入论文', project: '模型与技术资料',
};
const classLabels: Record<string, string> = {
  adenocarcinoma: '腺癌', squamous_cell_carcinoma: '鳞状细胞癌', large_cell_carcinoma: '大细胞癌', normal: '正常 / 筛查',
};
const statusLabels: Record<string, string> = {
  CURATED: '整理摘要 · 已启用', INDEX_ONLY: '仅索引 · 未入检索', PENDING: '待核对 · 未入检索',
  BLOCKED: '风险条目 · 禁止启用', DISABLED: '已停用', USER_REVIEWED: '用户笔记 · 已启用',
};
const sourceCategory = (source: Source) => source.metadata.category || 'project';
const isPending = (source: Source) => ['PENDING', 'BLOCKED', 'DISABLED'].includes(source.metadata.review_status || '');

function ReviewControls({ source, onSaved }: { source: Source; onSaved: () => Promise<void> }) {
  const [note, setNote] = useState(source.metadata.review_note || '');
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(enabled: boolean) {
    setBusy(true); setError('');
    try {
      const response = await apiFetch('/api/evidence/sources/' + encodeURIComponent(source.source_id) + '/review', {
        method: 'PUT', body: JSON.stringify({ enabled, note, acknowledged }),
      });
      if (!response.ok) throw new Error(await responseMessage(response, '核对状态保存失败'));
      await onSaved(); setAcknowledged(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败'); }
    finally { setBusy(false); }
  }
  if (source.metadata.retracted || source.metadata.preprint) return <p className="research-notice">检测到撤稿、关注声明或预印本标记，不能启用为当前参考依据。</p>;
  return <details className="paper-review">
    <summary>{source.retrieval_enabled ? '维护核对笔记 / 停用' : '阅读原文后核对入库'}</summary>
    <p>请自行阅读原文，填写原创中文要点、研究对象及局限。仅保存笔记，不复制论文全文。不填写患者身份信息。本机其他账号也可检索启用的笔记。</p>
    <label>核对笔记（20–2000字）<textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} rows={5} /></label>
    <label className="research-check"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />我已核对原文、适用范围及局限，确认仅用于科研参考，不代表临床审定。</label>
    <div className="research-actions"><button disabled={busy || !acknowledged || note.trim().length < 20} onClick={() => void save(true)}>保存笔记并启用检索</button>{source.retrieval_enabled && <button disabled={busy} onClick={() => void save(false)}>停用检索</button>}</div>
    {error && <p role="alert">{error}</p>}
  </details>;
}

export default function KnowledgeLibrary() {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [topics, setTopics] = useState<{ value: string; label: string }[]>([]);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('ALL');
  const [classFilter, setClassFilter] = useState('ALL');
  const [error, setError] = useState('');
  const [topic, setTopic] = useState('adenocarcinoma');
  const [since, setSince] = useState('2020');
  const [online, setOnline] = useState<SearchResult | null>(null);
  const [onlineError, setOnlineError] = useState('');
  const [notice, setNotice] = useState('');
  const [searching, setSearching] = useState(false);
  const [importing, setImporting] = useState('');

  const reload = useCallback(async () => {
    const response = await apiFetch('/api/evidence/sources', { cache: 'no-store' });
    if (!response.ok) throw new Error(await responseMessage(response, '资料库读取失败'));
    setPayload(await response.json() as Payload);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      apiFetch('/api/evidence/sources', { cache: 'no-store', signal: controller.signal }).then(async (response) => {
        if (!response.ok) throw new Error(await responseMessage(response, '资料库读取失败'));
        setPayload(await response.json() as Payload);
      }),
      apiFetch('/api/evidence/online/topics', { signal: controller.signal }).then(async (response) => {
        if (!response.ok) throw new Error(await responseMessage(response, '检索主题加载失败'));
        setTopics((await response.json() as { items: { value: string; label: string }[] }).items);
      }),
    ]).catch((reason) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '资料库读取失败'); });
    return () => controller.abort();
  }, []);

  const items = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (payload?.items || []).filter((item) => {
      if (category === 'pending' ? !isPending(item) : category !== 'ALL' && sourceCategory(item) !== category) return false;
      if (classFilter !== 'ALL' && !item.metadata.classes?.includes(classFilter)) return false;
      return !needle || [item.title, item.authority, item.scope, item.locator, item.metadata.original_title || '', item.metadata.doi || ''].some((value) => value.toLowerCase().includes(needle));
    }).sort((a, b) => (sourceCategory(a) === 'project' ? 1 : 0) - (sourceCategory(b) === 'project' ? 1 : 0));
  }, [payload, query, category, classFilter]);
  const pending = payload?.items.filter(isPending).length || 0;

  async function search() {
    setSearching(true); setOnlineError(''); setNotice(''); setOnline(null);
    try {
      const params = new URLSearchParams({ topic, since });
      const response = await apiFetch('/api/evidence/online/search?' + params, { cache: 'no-store' });
      if (!response.ok) throw new Error(await responseMessage(response, '在线检索失败'));
      setOnline(await response.json() as SearchResult);
    } catch (reason) { setOnlineError(reason instanceof Error ? reason.message : '在线检索失败'); }
    finally { setSearching(false); }
  }
  async function importPaper(pmid: string) {
    if (!online) return;
    setImporting(pmid); setOnlineError(''); setNotice('');
    try {
      const response = await apiFetch('/api/evidence/online/import', { method: 'POST', body: JSON.stringify({ pmid, topic: online.topic }) });
      if (!response.ok) throw new Error(await responseMessage(response, '论文导入失败'));
      const result = await response.json() as { notice: string };
      await reload(); setNotice(result.notice);
    } catch (reason) { setOnlineError(reason instanceof Error ? reason.message : '论文导入失败'); }
    finally { setImporting(''); }
  }

  return <main className="library-shell research-library">
    <header className="rag-topbar library-topbar">
      <a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>LUNG CANCER RESEARCH LIBRARY</small></span></a>
      <nav><BackToAgent /></nav>
    </header>
    <section className="library-layout">
      <aside className="library-sidebar">
        <div><span>KNOWLEDGE BASE</span><h1>肺癌科研资料库</h1><p>从细胞形态到CT征象，保留证据的来源、边界和核对状态。</p></div>
        <nav aria-label="资料库类型筛选">
          <button className={category === 'ALL' ? 'active' : ''} onClick={() => setCategory('ALL')}><span>全部资料</span><b>{payload?.counts.sources || 0}</b></button>
          {Object.entries(categoryLabels).map(([key, label]) => <button key={key} className={category === key ? 'active' : ''} onClick={() => setCategory(key)}><span>{label}</span><b>{payload?.items.filter((item) => sourceCategory(item) === key).length || 0}</b></button>)}
          <button className={category === 'pending' ? 'active' : ''} onClick={() => setCategory('pending')}><span>待核对 / 未启用</span><b>{pending}</b></button>
        </nav>
        <div className="library-scope"><span>本机共享 · 分层引用</span><p>{payload?.scope || '正在读取资料库…'}</p></div>
      </aside>
      <section className="library-content">
        <div className="library-hero"><div><span>MORPHOLOGY · CT · EVIDENCE</span><h2>让影像解读有据可查</h2><p>已整理肺癌诊疗、细胞病理、CT征象与分型研究。可以联网检索新的PubMed题录，阅读并核对后纳入本地参考。</p></div><div><strong>{payload?.counts.active_sources || 0}</strong><span>可检索来源</span><strong>{pending}</strong><span>待核对 / 未启用</span></div></div>
        <div className="research-notice"><strong>四分类 ≠ 四种癌细胞</strong><p>本项目识别腺癌、鳞状细胞癌、大细胞癌与正常肺部。细胞形态来自显微病理，CT只能提供间接的组织学预测线索；“正常”预测不等于排除肺癌。新增文献只扩充问答依据，不会重新训练影像模型。</p></div>
        <details className="online-research">
          <summary><span>在线论文检索</span><small>Europe PMC · PubMed题录 ↗</small></summary>
          <p>只发送预设公共医学主题，不发送CT、账号信息或对话内容。展示最新的前8条题录；摘要仅为短节选，完整内容请到原站阅读。</p>
          <form onSubmit={(event) => { event.preventDefault(); void search(); }} className="research-search-form">
            <label>检索主题<select value={topic} onChange={(event) => setTopic(event.target.value)} disabled={searching}>{topics.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
            <label>发表年份起<input type="number" min={2000} max={new Date().getFullYear()} value={since} onChange={(event) => setSince(event.target.value)} required disabled={searching} /></label>
            <button type="submit" disabled={searching || !topics.length}>{searching ? '正在连接论文数据库…' : '检索论文'}</button>
          </form>
          {onlineError && <p role="alert" className="research-error">{onlineError} 已有本地资料仍可使用。</p>}
          {notice && <p role="status" className="research-notice">{notice} 可在左侧“待核对 / 未启用”中处理。</p>}
          {online && <div aria-live="polite"><p>共 {online.total} 条匹配 · 本次展示 {online.items.length} 条 · 查询时间 {online.checked_at.slice(0, 10)}</p>
            {!online.items.length && <p>该主题和年份范围暂未找到题录，可调整年份后重试。</p>}
            <div className="online-paper-list">{online.items.map((paper) => {
              const existing = payload?.items.find((item) => item.metadata.pmid === paper.pmid);
              return <article key={paper.pmid}>
                <header><span>{paper.publication_date} · {paper.journal}</span><span>{paper.open_access ? '标记为开放获取，许可请查原站' : '访问权限请查原站'}</span></header>
                <h3>{paper.title}</h3><p className="paper-authors">{paper.authors}</p><p>{paper.abstract_preview || '题录无摘要，请查看原文。'}{paper.abstract_preview && '…'}</p>
                <small>PMID {paper.pmid}{paper.doi && ' · DOI ' + paper.doi}</small>
                {(paper.retracted || paper.preprint) && <p className="research-error">有撤稿/关注声明或预印本标记，不能启用检索。</p>}
                <div className="research-actions"><a href={paper.url} target="_blank" rel="noreferrer">查看PubMed原文入口 ↗</a><button disabled={!!importing || (!!existing && !existing.can_review)} onClick={() => void importPaper(paper.pmid)}>{importing === paper.pmid ? '正在核对题录…' : existing ? existing.can_review ? '重新核对上游题录' : '已在资料库' : '导入为待核对'}</button></div>
              </article>;
            })}</div>
          </div>}
        </details>
        <div className="research-class-filters" aria-label="肺部分类筛选"><button aria-pressed={classFilter === 'ALL'} onClick={() => setClassFilter('ALL')}>全部分类</button>{Object.entries(classLabels).map(([key, label]) => <button key={key} aria-pressed={classFilter === key} onClick={() => setClassFilter(key)}>{label}</button>)}</div>
        <div className="library-toolbar"><label><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="在已入库资料中搜索标题、PMID、DOI或来源" aria-label="搜索本地资料" /></label><em>{items.length} 项结果</em></div>
        {error && <div className="rag-alert" role="alert">{error}</div>}
        {!payload && !error && <div className="library-loading">正在读取本地资料索引…</div>}
        {payload && !items.length && <p>没有匹配资料。请调整筛选，或通过在线检索补充。</p>}
        <div className="source-grid">{items.map((item) => {
          const meta = item.metadata;
          const external = ['MEDICAL_NOTE', 'ONLINE_PAPER', 'DATASET_INDEX'].includes(item.source_type) && item.locator.startsWith('https://');
          return <article key={item.source_id}>
            <header><span>{categoryLabels[sourceCategory(item)]}</span><i>{statusLabels[meta.review_status || ''] || (item.retrieval_enabled ? '本地资料 · 已启用' : '未启用')}</i></header>
            <h3>{item.title}</h3>{meta.original_title && <p className="paper-original-title">{meta.original_title}</p>}
            <p>{meta.limitations || item.scope}</p>
            <div className="paper-class-tags">{meta.classes?.map((key) => <span key={key}>{classLabels[key] || key}</span>)}</div>
            <dl><div><dt>来源 / 机构</dt><dd>{item.authority}</dd></div><div><dt>发表 / 版本</dt><dd>{item.publication_date || item.version}</dd></div><div><dt>证据性质</dt><dd>{meta.evidence_level || '项目原始记录'}</dd></div><div><dt>内容核对</dt><dd>{meta.verification || meta.content_kind || '本地文件索引'}{meta.checked_at && ' · ' + meta.checked_at.slice(0, 10)}</dd></div></dl>
            {meta.pmid && <p className="paper-identifiers">PMID {meta.pmid}{meta.doi && ' · DOI ' + meta.doi}</p>}
            <footer><span title={item.locator}>{item.locator}</span><a href={apiBaseUrl + '/api/evidence/sources/' + encodeURIComponent(item.source_id) + '/content'} target="_blank" rel="noreferrer">{external ? item.source_type === 'DATASET_INDEX' ? '查看索引说明' : '查看整理内容' : '查看原始内容'} ↗</a>{external && <a href={item.locator} target="_blank" rel="noreferrer">访问原站 ↗</a>}</footer>
            {item.can_review && <ReviewControls key={item.source_id + '-' + meta.checked_at} source={item} onSaved={reload} />}
          </article>;
        })}</div>
      </section>
    </section>
  </main>;
}
