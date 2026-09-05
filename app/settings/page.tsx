'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import BackToAgent from '../back-to-agent';
import { apiFetch, responseMessage } from '../auth-client';
import CaseTable from '../cases/case-table';
import type { CaseTask } from '../cases/case-actions';

type ProviderId = 'openai' | 'kimi' | 'deepseek';
type ProviderSetting = {
  id: ProviderId;
  label: string;
  base_url: string;
  models: string[];
  configured: boolean;
  masked_key: string | null;
  model: string;
  status: 'NOT_CONFIGURED' | 'SAVED' | 'VERIFIED' | 'ERROR';
  last_error: string | null;
};
type Settings = { selected_provider: ProviderId; providers: ProviderSetting[] };
type Usage = { calls: number; input_tokens: number; output_tokens: number; total_tokens: number };

const providerNames: Record<ProviderId, string> = { openai: 'ChatGPT', kimi: 'Kimi', deepseek: 'DeepSeek' };
const providerCodes: Record<ProviderId, string> = { openai: 'AI', kimi: 'K', deepseek: 'DS' };

export default function SettingsCenter() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [usage, setUsage] = useState<Usage>({ calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0 });
  const [selectedId, setSelectedId] = useState<ProviderId>('openai');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'save' | 'test' | 'delete' | ''>('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveLoaded, setArchiveLoaded] = useState(false);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveItems, setArchiveItems] = useState<CaseTask[]>([]);
  const [archiveError, setArchiveError] = useState('');

  const loadSettings = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [settingsResponse, usageResponse] = await Promise.all([
        apiFetch('/api/settings/llm', { cache: 'no-store' }),
        apiFetch('/api/agent/usage', { cache: 'no-store' }),
      ]);
      if (!settingsResponse.ok) throw new Error(await responseMessage(settingsResponse, '无法读取模型设置'));
      const payload = await settingsResponse.json() as Settings;
      setSettings(payload);
      setSelectedId(payload.selected_provider);
      setModel(payload.providers.find((item) => item.id === payload.selected_provider)?.model || '');
      if (usageResponse.ok) setUsage(await usageResponse.json());
    } catch (reason) { setError(reason instanceof Error ? reason.message : '设置中心加载失败'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { const timer = window.setTimeout(() => { void loadSettings(); }, 0); return () => window.clearTimeout(timer); }, [loadSettings]);

  const loadArchivedCases = useCallback(async () => {
    setArchiveLoading(true); setArchiveError('');
    try {
      const response = await apiFetch('/api/tasks?archived=true&limit=500', { cache: 'no-store' });
      if (!response.ok) throw new Error(await responseMessage(response, '无法读取已归档病例'));
      const payload = await response.json() as { items: CaseTask[] };
      setArchiveItems(payload.items); setArchiveLoaded(true);
    } catch (reason) { setArchiveError(reason instanceof Error ? reason.message : '无法读取已归档病例'); }
    finally { setArchiveLoading(false); }
  }, []);

  const showArchive = () => {
    setArchiveOpen(true);
    if (!archiveLoaded) void loadArchivedCases();
    window.requestAnimationFrame(() => document.getElementById('archived-cases')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  const selected = useMemo(() => settings?.providers.find((item) => item.id === selectedId), [selectedId, settings]);
  const chooseProvider = (provider: ProviderSetting) => {
    setSelectedId(provider.id); setModel(provider.model); setApiKey(''); setNotice(''); setError('');
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    if (!selected.configured && apiKey.trim().length < 12) { setError(`请输入有效的${providerNames[selectedId]} API Key`); return; }
    setBusy('save'); setNotice(''); setError('');
    try {
      const response = await apiFetch('/api/settings/llm', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: selectedId, api_key: apiKey.trim() || null, model }),
      });
      if (!response.ok) throw new Error(await responseMessage(response, '保存失败'));
      setSettings(await response.json()); setApiKey(''); setNotice(`${providerNames[selectedId]}已保存并启用。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败'); }
    finally { setBusy(''); }
  };

  const testConnection = async () => {
    if (!selected?.configured) return;
    setBusy('test'); setNotice(''); setError('');
    try {
      const response = await apiFetch('/api/settings/llm/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: selectedId }) });
      if (!response.ok) throw new Error(await responseMessage(response, '连接测试失败'));
      setSettings(await response.json()); setNotice(`${providerNames[selectedId]}连接验证成功。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '连接测试失败'); }
    finally { setBusy(''); }
  };

  const removeProvider = async () => {
    if (!selected?.configured || !window.confirm(`删除${providerNames[selectedId]}的本地API配置？此操作不会删除服务商账户。`)) return;
    setBusy('delete'); setNotice(''); setError('');
    try {
      const response = await apiFetch(`/api/settings/llm/${selectedId}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(await responseMessage(response, '删除配置失败'));
      const payload = await response.json() as Settings;
      setSettings(payload); setApiKey(''); setModel(payload.providers.find((item) => item.id === selectedId)?.model || ''); setNotice('本地API配置已删除。');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '删除配置失败'); }
    finally { setBusy(''); }
  };

  return <main className="settings-shell">
    <header className="settings-topbar"><a href="/agent" className="review-brand"><span className="brand-mark" /><span><b>LungSight</b><small>SETTINGS CENTER</small></span></a><BackToAgent /></header>
    <div className="settings-layout">
      <aside className="settings-nav"><span>SETTINGS</span><h1>设置中心</h1><nav><a className="active" href="#model-services"><i>AI</i><span><b>模型服务</b><small>API、模型与连接状态</small></span></a><button type="button" onClick={showArchive}><i>AR</i><span><b>查看归档</b><small>恢复或永久删除病例</small></span></button><a href="#local-data"><i>DB</i><span><b>本地数据</b><small>存储、备份与隐私</small></span></a><a href="/agent"><i>←</i><span><b>返回医学问答</b><small>继续当前工作</small></span></a></nav></aside>
      <section className="settings-content" id="model-services">
        <div className="settings-heading"><div><span>MODEL SERVICES</span><h2>模型服务</h2><p>主页顶部只用于快速切换已配置模型；API Key与连接测试统一在此管理。</p></div><strong className={settings?.providers.some((item) => item.configured) ? 'online' : ''}>{settings?.providers.filter((item) => item.configured).length || 0} / 3 已配置</strong></div>
        {loading ? <div className="settings-loading">正在读取加密配置…</div> : <>
          <section className="settings-usage"><div><span>ACCOUNT USAGE</span><b>本账号累计Token用量</b></div><strong>{usage.total_tokens.toLocaleString()} <small>tokens</small></strong><p>{usage.calls} 次模型生成 · 输入 {usage.input_tokens.toLocaleString()} / 输出 {usage.output_tokens.toLocaleString()}</p></section>
          <div className="settings-provider-grid">{settings?.providers.map((provider) => <button type="button" key={provider.id} className={`${provider.id === selectedId ? 'selected' : ''} ${provider.id === settings.selected_provider ? 'active' : ''}`} onClick={() => chooseProvider(provider)}><i>{providerCodes[provider.id]}</i><span><b>{providerNames[provider.id]}</b><small>{provider.configured ? `${provider.masked_key} · ${provider.status === 'VERIFIED' ? '连接已验证' : '已加密保存'}` : '尚未配置API Key'}</small></span>{provider.id === settings.selected_provider && <em>当前启用</em>}</button>)}</div>
          <form className="settings-provider-form" onSubmit={save}>
            <header><div><span>PROVIDER CONFIGURATION</span><h3>{providerNames[selectedId]}</h3></div><strong>{selected?.configured ? '已配置' : '待配置'}</strong></header>
            <label><span>API Key</span><input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={selected?.masked_key || `输入${providerNames[selectedId]} API Key`} /><small>{selected?.configured ? '留空表示保留当前密钥；输入新Key将替换原配置。' : '密钥仅在本机后端加密保存，不写入浏览器存储。'}</small></label>
            <label><span>模型</span><select value={model} onChange={(event) => setModel(event.target.value)}>{selected?.models.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            <div className="settings-form-actions"><button disabled={!!busy}>{busy === 'save' ? '正在保存…' : selected?.configured && !apiKey ? '切换并启用' : '保存并启用'}</button><button type="button" disabled={!selected?.configured || !!busy} onClick={() => void testConnection()}>{busy === 'test' ? '正在测试…' : '测试连接'}</button><button type="button" className="danger" disabled={!selected?.configured || !!busy} onClick={() => void removeProvider()}>{busy === 'delete' ? '正在删除…' : '删除配置'}</button></div>
            {notice && <p className="settings-notice" role="status">✓ {notice}</p>}{error && <p className="settings-error" role="alert">{error}</p>}{selected?.last_error && <p className="settings-error">最近错误：{selected.last_error}</p>}
          </form>
          <section className="settings-data" id="local-data"><div><span>LOCAL DATA & PRIVACY</span><h3>本地数据与隐私</h3></div><div className="settings-data-grid"><article><i>DB</i><b>本地数据库</b><p>账号、历史问答、病例、引用和审计记录保存在本机。</p></article><article><i>SK</i><b>密钥保护</b><p>不同服务商的API Key独立加密，切换不会覆盖其他配置。</p></article><article><i>PHI</i><b>隐私提醒</b><p>提问和病例名称中不要填写姓名、手机号、身份证号等身份信息。</p></article></div></section>
          <section className="settings-archive" id="archived-cases">
            <button type="button" className="settings-archive-toggle" aria-expanded={archiveOpen} onClick={() => { const next = !archiveOpen; setArchiveOpen(next); if (next && !archiveLoaded) void loadArchivedCases(); }}>
              <span><i>ARCHIVED CASES</i><b>已归档病例</b><small>归档不会删除任何数据；可以恢复到病例库，或在确认后永久删除。</small></span><em>{archiveItems.length || '—'}</em><strong aria-hidden="true">{archiveOpen ? '收起 −' : '查看 +'}</strong>
            </button>
            {archiveOpen && <div className="settings-archive-list">{archiveError && <p className="settings-error" role="alert">{archiveError}</p>}<CaseTable archived items={archiveItems} loading={archiveLoading} emptyText="还没有已归档病例。病例库中右键选择“归档病例”后会显示在这里。" onRefresh={loadArchivedCases} /></div>}
          </section>
        </>}
      </section>
    </div>
  </main>;
}
