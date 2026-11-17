'use client';

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { apiFetch, responseMessage } from '../auth-client';
import type { AuthUser } from '../auth-client';
import AccountMenu from './account-menu';
import { useWorkspaceAppearance } from '../appearance-provider';
import { UserAvatar } from './profile-editor';
import HistoryList from './history-list';
import type { HistoryConversation } from './history-actions';
import { useChatScroll } from './use-chat-scroll';
import './chat-scroll.css';
import WorkspaceClock from './workspace-clock';
import './agent-emblem.css';

type Citation = { citation_id: string; source_id: string; title: string; excerpt: string; locator: string; page_number: number | null; section?: string; verified?: boolean };
type AgentResponse = { answer?: string; support_level?: string; risk_level?: string; uncertainty?: string[]; next_steps?: string[]; disclaimer?: string; citation_ids?: string[]; answer_mode?: 'grounded' | 'medical_general' | 'ct_hybrid'; knowledge_sources?: string[] };
type Message = { message_id: string; role: 'user' | 'assistant'; content: string; created_at: string; support_level?: string; risk_level?: string; provider?: string; model?: string; total_tokens?: number; response?: AgentResponse; citations?: Citation[]; streaming?: boolean };
type Conversation = HistoryConversation;
type Task = { task_id: string; created_at: string; top_class_cn: string; reliability_level: string; status: string; top_probability: number };
type ProviderSetting = { id: 'openai' | 'kimi' | 'deepseek'; label: string; base_url: string; models: string[]; configured: boolean; masked_key: string | null; model: string; status: 'NOT_CONFIGURED' | 'SAVED' | 'VERIFIED' | 'ERROR'; last_error: string | null };
type Settings = { selected_provider: ProviderSetting['id']; providers: ProviderSetting[] };
type Usage = { calls: number; input_tokens: number; output_tokens: number; total_tokens: number };

const supportLabel: Record<string, string> = { SUPPORTED: '证据支持', PARTIALLY_SUPPORTED: '部分支持', INSUFFICIENT: '证据不足', REFUSED: '安全拒答', MIXED: '本地摘录 + 模型解读', GENERAL_KNOWLEDGE: '模型医学知识' };
const medicalPrompts = ['肺结节和肺癌有什么区别？', 'CT检查和病理检查各能说明什么？', '肺癌常见的分期方法是什么？', '靶向治疗与免疫治疗的基本原理是什么？'];
const ctPrompts = ['请结合当前CT结果说明需要复核的重点。', '五折模型概率平均的目的是什么？', '模型分类概率能否等同于患癌概率？', '本地资料和通用医学知识有哪些适用范围差异？'];
const workspaceModules = [
  { href: '/agent', code: 'AI', title: '医学Agent问答', detail: '通用医学知识 · 支持病例解读', active: true },
  { href: '/analysis', code: 'CT', title: '肺部CT影像分析', detail: '上传、五折识别与质控' },
  { href: '/review', code: 'RP', title: '复核与报告中心', detail: '判别依据、医生结论与下载' },
  { href: '/library', code: 'KB', title: '肺癌科研资料库', detail: '浏览已核验的本地知识来源' },
] as const;
const providerShortName: Record<ProviderSetting['id'], string> = { openai: 'ChatGPT', kimi: 'Kimi', deepseek: 'DeepSeek' };
const date = (value: string) => new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));

const ChatMessage = memo(function ChatMessage({ message, user, onRetry }: { message: Message; user: AuthUser | null; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(message.content);
    setCopied(true); window.setTimeout(() => setCopied(false), 1400);
  };
  return <article className={`chat-message ${message.role}`}>
    <div className="message-avatar">{message.role === 'user' ? <UserAvatar user={user} /> : 'LS'}</div>
    <div className="message-body">
      <header><strong>{message.role === 'user' ? '你' : 'LungSight Agent'}</strong><time>{date(message.created_at)}</time>{message.support_level && <i className={message.support_level.toLowerCase()}>{supportLabel[message.support_level] || message.support_level}</i>}{message.risk_level === 'HIGH' && <i className="risk">高风险已拦截</i>}</header>
      <p>{message.content || (message.streaming ? '正在检索与核验引用…' : '')}<span className={message.streaming ? 'typing' : ''} /></p>
      {message.role === 'assistant' && message.response && <>
        {!!message.response.uncertainty?.length && <div className="uncertainty-box"><b>不确定性</b>{message.response.uncertainty.map((item) => <span key={item}>{item}</span>)}</div>}
        {!!message.citations?.length && <div className="inline-citations">{message.citations.map((citation) => <button key={citation.citation_id} title={citation.excerpt}>{citation.citation_id} · {citation.title}{citation.verified !== false && <i>✓</i>}</button>)}</div>}
        <footer><span>{message.response.answer_mode === 'ct_hybrid' ? 'CT综合解读' : message.response.answer_mode === 'medical_general' ? '医学通用问答' : '本地循证问答'} · {message.provider} · {message.model}</span><span>{message.total_tokens || 0} tokens</span><button type="button" onClick={() => void copy()}>{copied ? '已复制' : '复制'}</button>{onRetry && <button type="button" onClick={onRetry}>再次提问</button>}</footer>
      </>}
    </div>
  </article>;
});

export default function AgentWorkspace() {
  const { appearance, changeAppearance, preferenceNotice } = useWorkspaceAppearance();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [usage, setUsage] = useState<Usage>({ calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0 });
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [linkedTaskId, setLinkedTaskId] = useState('');
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [switchingProvider, setSwitchingProvider] = useState(false);
  const [rightRailOpen, setRightRailOpen] = useState(true);
  const [globalQuery, setGlobalQuery] = useState('');
  const { scrollRef: messageScrollRef, contentRef: messageContentRef, onScroll: onMessageScroll, pauseFollowing, followLatest, showLatest } = useChatScroll(messages, activeId, !loading);
  const historyLibrary = useRef<HTMLDetailsElement | null>(null);
  const historyLoadVersion = useRef(0);
  const streamController = useRef<AbortController | null>(null);

  const loadConversation = useCallback(async (conversationId: string) => {
    const version = ++historyLoadVersion.current;
    setError('');
    const response = await apiFetch(`/api/agent/conversations/${conversationId}`, { cache: 'no-store' });
    if (version !== historyLoadVersion.current) return;
    if (!response.ok) throw new Error(await responseMessage(response, '无法读取对话'));
    const payload = await response.json() as Conversation & { messages: Message[] };
    if (version !== historyLoadVersion.current) return;
    setActiveId(conversationId);
    setLinkedTaskId(payload.linked_task_id || '');
    setMessages(payload.messages);
  }, []);

  const refreshLists = useCallback(async () => {
    const [conversationResponse, usageResponse] = await Promise.all([apiFetch('/api/agent/conversations', { cache: 'no-store' }), apiFetch('/api/agent/usage', { cache: 'no-store' })]);
    if (conversationResponse.ok) {
      const payload: { items: Conversation[] } = await conversationResponse.json();
      setConversations(payload.items);
    }
    if (usageResponse.ok) setUsage(await usageResponse.json());
  }, []);

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    try {
      const [meResponse, settingsResponse, conversationsResponse, tasksResponse, usageResponse] = await Promise.all([
        apiFetch('/api/auth/me', { cache: 'no-store' }), apiFetch('/api/settings/llm', { cache: 'no-store' }),
        apiFetch('/api/agent/conversations', { cache: 'no-store' }), apiFetch('/api/tasks?limit=40', { cache: 'no-store' }),
        apiFetch('/api/agent/usage', { cache: 'no-store' }),
      ]);
      if (!meResponse.ok || !settingsResponse.ok || !conversationsResponse.ok) throw new Error('无法读取Agent工作区');
      const me: { user: AuthUser } = await meResponse.json();
      const providerSettings = await settingsResponse.json() as Settings;
      const historyPayload: { items: Conversation[] } = await conversationsResponse.json();
      const history = historyPayload.items;
      setUser(me.user); setSettings(providerSettings); setConversations(history);
      if (tasksResponse.ok) {
        const taskPayload: { items: Task[] } = await tasksResponse.json();
        const taskItems = taskPayload.items;
        setTasks(taskItems);
        const requestedTask = new URLSearchParams(window.location.search).get('task');
        if (requestedTask && taskItems.some((task) => task.task_id === requestedTask)) {
          setLinkedTaskId(requestedTask);
          setQuestion(new URLSearchParams(window.location.search).get('focus')?.slice(0, 1000) || '请结合当前CT结构化结果、本地资料和通用医学知识，说明模型输出、可靠性、局限性，以及医生需要重点复核的内容，并区分信息来源。');
        }
      }
      if (usageResponse.ok) setUsage(await usageResponse.json());
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Agent工作区加载失败'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadWorkspace(); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadWorkspace]);

  useEffect(() => {
    if (loading) return;
    const key = `lungsight-agent-draft:${linkedTaskId || 'general'}`;
    const timer = window.setTimeout(() => window.localStorage.setItem(key, question), 250);
    return () => window.clearTimeout(timer);
  }, [linkedTaskId, loading, question]);

  useEffect(() => {
    if (messages.length) return;
    const saved = window.localStorage.getItem(`lungsight-agent-draft:${linkedTaskId || 'general'}`);
    if (!saved) return;
    const timer = window.setTimeout(() => setQuestion(saved), 0);
    return () => window.clearTimeout(timer);
  }, [linkedTaskId, messages.length]);

  const newConversation = () => { historyLoadVersion.current++; followLatest(); setActiveId(null); setMessages([]); setLinkedTaskId(''); setQuestion(''); setError(''); };

  const sendQuestion = async (event?: FormEvent) => {
    event?.preventDefault();
    const clean = question.trim();
    if (!clean || sending) return;
    followLatest();
    setSending(true); setError(''); setQuestion('');
    window.localStorage.removeItem(`lungsight-agent-draft:${linkedTaskId || 'general'}`);
    let conversationId = activeId;
    try {
      if (!conversationId) {
        const created = await apiFetch('/api/agent/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: clean.slice(0, 42), linked_task_id: linkedTaskId || null }) });
        if (!created.ok) throw new Error(await responseMessage(created, '无法新建对话'));
        const createdConversation: { conversation_id: string } = await created.json();
        conversationId = createdConversation.conversation_id; setActiveId(conversationId);
      }
      const assistantId = `local-assistant-${Date.now()}`;
      setMessages((current) => [...current, { message_id: `local-user-${Date.now()}`, role: 'user', content: clean, created_at: new Date().toISOString() }, { message_id: assistantId, role: 'assistant', content: '', created_at: new Date().toISOString(), streaming: true }]);
      const controller = new AbortController(); streamController.current = controller;
      const response = await apiFetch('/api/agent/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: clean, conversation_id: conversationId, linked_task_id: linkedTaskId || null }), signal: controller.signal });
      if (!response.ok) throw new Error(await responseMessage(response, 'Agent回答失败'));
      if (!response.body) throw new Error('浏览器未收到流式响应');
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split('\n'); buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.trim()) continue;
          const streamEvent = JSON.parse(line);
          if (streamEvent.type === 'delta') setMessages((current) => current.map((item) => item.message_id === assistantId ? { ...item, content: item.content + streamEvent.delta } : item));
          if (streamEvent.type === 'done') {
            const result = streamEvent.result;
            setMessages((current) => current.map((item) => item.message_id === assistantId ? { ...item, message_id: result.message_id, content: result.answer, streaming: false, support_level: result.support_level, risk_level: result.risk_level, provider: result.provider, model: result.model, total_tokens: result.usage.total_tokens, response: result, citations: result.citations } : item));
          }
        }
        if (done) break;
      }
      await refreshLists();
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') {
        setMessages((current) => current.map((item) => item.streaming ? { ...item, streaming: false, content: `${item.content}\n\n回答已由用户停止。` } : item));
        return;
      }
      setMessages((current) => current.filter((item) => !item.message_id.startsWith('local-')));
      setError(reason instanceof Error ? reason.message : 'Agent回答失败');
    } finally { streamController.current = null; setSending(false); }
  };

  const stopAnswer = () => streamController.current?.abort();

  const quickSwitchProvider = async (provider: ProviderSetting) => {
    if (!provider.configured || switchingProvider || provider.id === settings?.selected_provider) return;
    setSwitchingProvider(true); setError('');
    try {
      const response = await apiFetch('/api/settings/llm/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: provider.id, model: provider.model }) });
      if (!response.ok) throw new Error(await responseMessage(response, '模型切换失败'));
      setSettings(await response.json());
    } catch (reason) { setError(reason instanceof Error ? reason.message : '模型切换失败'); }
    finally { setSwitchingProvider(false); }
  };

  const submitGlobalSearch = (event: FormEvent) => {
    event.preventDefault();
    const query = globalQuery.trim();
    if (!query) return;
    const task = tasks.find((item) => item.task_id.toLowerCase().includes(query.toLowerCase()));
    if (task) { window.location.href = `/case?task=${encodeURIComponent(task.task_id)}`; return; }
    const conversation = conversations.find((item) => item.title.toLowerCase().includes(query.toLowerCase()));
    if (conversation) { void loadConversation(conversation.conversation_id); setGlobalQuery(''); return; }
    setQuestion(query); setGlobalQuery('');
  };

  const openHistory = () => {
    if (historyLibrary.current) {
      historyLibrary.current.open = true;
      historyLibrary.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      historyLibrary.current.querySelector('summary')?.focus();
    }
  };
  const activeCitations = useMemo(() => [...messages].reverse().find((item) => item.role === 'assistant')?.citations || [], [messages]);
  const linkedTask = tasks.find((task) => task.task_id === linkedTaskId);
  const activeProvider = settings?.providers.find((item) => item.id === settings.selected_provider);
  const waitingTasks = tasks.filter((task) => task.status === 'WAITING_FOR_REVIEW').length;

  return <main className="rag-shell">
    <header className="rag-topbar">
      <a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>CLINICAL AI WORKSPACE</small></span></a>
      <form className="workspace-search" onSubmit={submitGlobalSearch}><span aria-hidden="true">⌕</span><input value={globalQuery} onChange={(event) => setGlobalQuery(event.target.value)} placeholder="搜索病例或历史问答" aria-label="搜索病例或历史问答" /></form>
      <div className="rag-system-state">
        <span className="medical-mode"><i /> 医学专用</span>
        <details className="model-quick-switch"><summary className={activeProvider?.configured ? 'ready' : 'warning'}>{activeProvider?.configured ? `${providerShortName[activeProvider.id]} · ${activeProvider.model}` : '模型服务未配置'}<b aria-hidden="true">⌄</b></summary><div>{settings?.providers.filter((provider) => provider.configured).map((provider) => <button type="button" key={provider.id} disabled={switchingProvider || provider.id === settings.selected_provider} onClick={() => void quickSwitchProvider(provider)}><span>{providerShortName[provider.id]}<small>{provider.model}</small></span>{provider.id === settings.selected_provider && <i>当前</i>}</button>)}<a href="/settings">模型服务设置 →</a></div></details>
        <nav className="top-action-nav" aria-label="常用工作入口">
          <a href="/library" aria-label="打开肺癌科研资料库"><i>KB</i><span><b>资料库</b><small>循证文献</small></span></a>
          <a href="/evaluation" aria-label="打开Agent专项评测"><i>EV</i><span><b>专项评测</b><small>质量检查</small></span></a>
          <a href="/review" className="review-entry" aria-label={`打开复核任务，${waitingTasks}个待复核病例`}><i>RV</i><span><b>复核任务</b><small>{waitingTasks ? `${waitingTasks}个待处理` : '暂无待处理'}</small></span>{waitingTasks > 0 && <em>{waitingTasks}</em>}</a>
        </nav>
        <AccountMenu user={user} onUserUpdated={setUser} activeConversationId={activeId} busy={sending || switchingProvider} onOpenHistory={openHistory} appearance={appearance} onAppearanceChange={changeAppearance} preferenceNotice={preferenceNotice} />
      </div>
    </header>

    {loading ? <section className="rag-loading">正在建立加密会话与循证检索上下文…</section> : <section className={`rag-workspace ${rightRailOpen ? '' : 'right-collapsed'}`}>
      <aside className="conversation-rail">
        <div className="workspace-heading"><span>WORKSPACE</span><strong>临床辅助工作台</strong></div>
        <nav className="workspace-module-nav" aria-label="Agent功能导航">
          {workspaceModules.map((item) => <a key={item.href} href={item.href} className={item.href === '/agent' ? 'active' : ''}><i>{item.code}</i><span><strong>{item.title}</strong><small>{item.detail}</small></span><em>›</em></a>)}
          <a href="/cases"><i>CS</i><span><strong>病例库</strong><small>检索、状态和病例工作区</small></span><em>›</em></a>
          <a href="/settings"><i>ST</i><span><strong>设置中心</strong><small>模型服务、账号与本地数据</small></span><em>›</em></a>
        </nav>
        <div className="rail-separator" />
        <button className="new-chat" onClick={newConversation}>＋ 新建医学对话</button>
        <details ref={historyLibrary} className="history-library">
          <summary>
            <i>HX</i>
            <span><strong>历史问答库</strong><small>展开检查之前的询问记录</small></span>
            <em>{conversations.length}</em>
            <b aria-hidden="true">⌄</b>
          </summary>
          <HistoryList items={conversations} activeId={activeId} busy={sending} onSelect={loadConversation}
            onDeleted={(id) => { historyLoadVersion.current++; setConversations((current) => current.filter((item) => item.conversation_id !== id)); if (activeId === id) newConversation(); }}
            onPinUpdated={(id, pinnedAt) => setConversations((current) => current.map((item) => item.conversation_id === id ? { ...item, pinned_at: pinnedAt } : item))} />
        </details>
      </aside>

      <section className="chat-stage">
        <div className="chat-context-bar"><div><span>ACTIVE CONTEXT</span><strong>{linkedTask ? `CT综合解读 · ${linkedTask.task_id}` : '医学通用问答 · 模型医学知识'}</strong></div><div className="context-actions"><select aria-label="关联CT病例" value={linkedTaskId} onChange={(event) => setLinkedTaskId(event.target.value)} disabled={messages.length > 0}><option value="">不关联CT病例</option>{tasks.map((task) => <option value={task.task_id} key={task.task_id}>{task.task_id} · {task.top_class_cn}</option>)}</select><button type="button" onClick={() => setRightRailOpen((value) => !value)} aria-expanded={rightRailOpen}>{rightRailOpen ? '隐藏辅助栏' : '显示辅助栏'}</button></div></div>
        {error && <div className="rag-alert">{error}{!activeProvider?.configured && <span> · 请前往设置中心配置模型服务</span>}</div>}
        <div className="message-pane">
        <div ref={messageScrollRef} className="message-scroll" role="region" aria-label="医学问答内容，可上下滚动" tabIndex={0}
          onScroll={onMessageScroll}
          onWheel={(event) => { if (event.deltaY < 0) pauseFollowing(); }}
          onKeyDown={(event) => { if (['ArrowUp', 'PageUp', 'Home'].includes(event.key)) pauseFollowing(); }}>
          <div ref={messageContentRef} className="message-content">
          {!messages.length && <section className="chat-empty"><div className="agent-orb" role="img" aria-label="当前账号头像"><span><UserAvatar user={user} /></span></div><span>LUNGSIGHT CLINICAL WORKSPACE</span><WorkspaceClock /><p>可询问疾病、检查、药理和医学科研问题，不再要求本地资料必须命中。关联CT后，将结合本地资料、当前结构化结果与模型医学知识解读。仅回答医学相关内容，个体诊疗决定仍需医生复核。</p><div className="workspace-shortcuts"><a href="/analysis"><i>CT</i><span><b>上传肺部CT影像</b><small>五折分类 · 质控 · Grad-CAM</small></span><em>↗</em></a><a href="/review"><i>RP</i><span><b>查看分析与报告</b><small>医生复核 · 循证依据 · 下载报告</small></span><em>↗</em></a><a href="/library"><i>KB</i><span><b>浏览肺癌资料库</b><small>论文 · 诊疗资料 · 技术文档</small></span><em>↗</em></a></div><div className="prompt-grid">{(linkedTask ? ctPrompts : medicalPrompts).map((prompt) => <button key={prompt} onClick={() => setQuestion(prompt)}>{prompt}<i>↗</i></button>)}</div></section>}
          {messages.map((message, index) => <ChatMessage key={message.message_id} message={message} user={user} onRetry={message.role === 'assistant' && index === messages.length - 1 && !message.streaming ? () => { const previous = [...messages].slice(0, index).reverse().find((item) => item.role === 'user'); if (previous) setQuestion(previous.content); } : undefined} />)}
          </div>
        </div>
        {showLatest && <button type="button" className="chat-jump-latest" onClick={followLatest}>↓ 回到最新</button>}
        </div>
        <form className="chat-composer" onSubmit={sendQuestion}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={linkedTask ? "结合当前CT、本地资料与医学知识提问…" : "询问疾病、检查、药理或医学科研问题…"} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendQuestion(); } }} /><div><span>草稿会自动保存在本机 · Enter发送 / Shift+Enter换行</span>{sending ? <button type="button" className="stop-answer" onClick={stopAnswer}>停止生成 ■</button> : <button disabled={!question.trim()}>发送问题 ↑</button>}</div></form>
        <p className="chat-disclaimer">仅回答医学相关问题。模型知识未实时核验，不替代医生诊疗；CT分类不等于确诊。紧急情况请联系当地急救服务。</p>
      </section>

      <aside className="evidence-rail">
        <section className="context-card"><div><span>CASE CONTEXT</span><strong>CT结构化上下文</strong></div>{linkedTask ? <><b>{linkedTask.task_id}</b><p>{linkedTask.top_class_cn} · {(linkedTask.top_probability * 100).toFixed(1)}%</p><small>{linkedTask.reliability_level} · {linkedTask.status}</small><a href={`/case?task=${linkedTask.task_id}`}>打开病例工作区 ↗</a></> : <p>当前使用模型通用医学知识回答，可参考相关本地资料；不关联任何CT病例。选择病例后自动切换为CT综合解读。</p>}</section>
        <section className="citation-panel"><div><span>VERIFIED SOURCES</span><strong>本轮证据引用</strong><em>{activeCitations.length}</em></div>{!activeCitations.length && <p>本轮暂无本地引用。模型通用知识不标为已核验文献；引用卡片仅核对来源及摘录，不代表临床验证。</p>}{activeCitations.map((citation) => <article key={citation.citation_id}><header><b>{citation.citation_id}</b><span>{citation.verified !== false ? '✓ 来源已核对' : '待核验'}</span></header><strong>{citation.title}</strong><p>{citation.excerpt}</p><footer><span>{citation.page_number ? `第${citation.page_number}页` : citation.section || '结构化记录'}</span><small>{citation.locator}</small></footer></article>)}</section>
        <div className="usage-card usage-card-provider"><span>ACCOUNT USAGE · 本账号累计用量</span><strong>{usage.total_tokens.toLocaleString()} <small>tokens</small></strong><p>{usage.calls} 次模型生成 · 输入 {usage.input_tokens.toLocaleString()} / 输出 {usage.output_tokens.toLocaleString()}</p></div>
        <section className="provider-status-card"><span>MODEL PROVIDER</span><strong>{activeProvider?.configured ? `${providerShortName[activeProvider.id]} · ${activeProvider.model}` : '尚未配置模型服务'}</strong><p>{activeProvider?.configured ? '顶部可快速切换已配置模型；API Key仅在设置中心管理。' : '配置API Key并启用模型后，才可生成医学问答。'}</p><a href="/settings">打开模型服务设置 →</a></section>
      </aside>
    </section>}
  </main>;
}
