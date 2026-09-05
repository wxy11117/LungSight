'use client';

import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { apiBaseUrl, apiFetch, responseMessage } from '../auth-client';
import type { AuthUser } from '../auth-client';
import { version } from '../../package.json';
import './account-menu.css';
import ProfileEditor, { UserAvatar } from './profile-editor';
import DoctorProfileDetails from './doctor-profile';
import { themes, accents } from '../appearance';
import type { Appearance } from '../appearance';

type ExportConversation = { conversation_id: string; title: string; linked_task_id: string | null; created_at: string; messages: Record<string, unknown>[] };
type LocalAccount = { user_id: string; display_name: string; identity_hint: string | null; last_login_at: string | null; is_current: boolean; avatar_url: string | null };

type Props = {
  user: AuthUser | null;
  onUserUpdated: (user: AuthUser) => void;
  activeConversationId: string | null;
  busy: boolean;
  onOpenHistory: () => void;
  appearance: Appearance;
  onAppearanceChange: (next: Appearance) => void;
  preferenceNotice: string;
};

function LogoutConfirm({ leaving, error, onCancel, onConfirm }: { leaving: boolean; error: string; onCancel: () => void; onConfirm: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => { if (dialog?.open) dialog.close(); };
  }, []);

  return <dialog ref={dialogRef} className="logout-confirm" aria-labelledby={headingId} onCancel={(event) => { if (leaving) event.preventDefault(); else onCancel(); }} onClose={() => { if (!leaving) onCancel(); }}>
    <span className="logout-confirm-icon" aria-hidden="true">↪</span>
    <h2 id={headingId}>确认退出登录？</h2>
    <p>退出后将返回登录页面。本机后端中已保存的账号资料、问答记录和CT任务不会被删除。</p>
    {error && <p className="logout-confirm-error" role="alert">{error}</p>}
    <footer>
      <button type="button" disabled={leaving} onClick={onCancel}>取消</button>
      <button type="button" className="logout-confirm-primary" disabled={leaving} onClick={onConfirm}>{leaving ? '正在退出…' : '确认退出'}</button>
    </footer>
  </dialog>;
}

function LocalAccountAvatar({ account }: { account: LocalAccount }) {
  const [failed, setFailed] = useState(false);
  return <span className="account-switch-avatar" aria-hidden="true">{account.avatar_url && !failed ?
    // Protected local avatars are loaded with the active session cookie.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={`${apiBaseUrl}${account.avatar_url}`} alt="" onError={() => setFailed(true)} /> :
    Array.from(account.display_name.trim() || 'U')[0].toLocaleUpperCase()}</span>;
}

function AccountSwitcher({ currentUserId, onClose }: { currentUserId: string; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const headingId = useId();
  const [accounts, setAccounts] = useState<LocalAccount[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const dialog = dialogRef.current;
    const controller = new AbortController();
    dialog?.showModal();
    void apiFetch('/api/auth/accounts', { cache: 'no-store', signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error(await responseMessage(response, '无法读取本机账号，请稍后重试。'));
      const payload: { items?: LocalAccount[] } = await response.json();
      const items = Array.isArray(payload.items) ? payload.items : [];
      setAccounts(items);
      setSelectedId(items.find((account) => !account.is_current)?.user_id || items[0]?.user_id || '');
    }).catch((reason) => {
      if (reason instanceof Error && reason.name !== 'AbortError') setError(reason.message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); if (dialog?.open) dialog.close(); };
  }, []);

  const chooseAccount = (accountId: string) => {
    setSelectedId(accountId); setPassword(''); setError('');
    requestAnimationFrame(() => passwordRef.current?.focus());
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedId || !password || switching) return;
    setSwitching(true); setError('');
    try {
      const response = await apiFetch('/api/auth/switch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: selectedId, password }),
      });
      if (!response.ok) throw new Error(await responseMessage(response, '账号验证失败，请重新输入密码。'));
      window.location.replace('/agent');
    } catch (reason) {
      setError(reason instanceof TypeError ? '无法连接本地服务，当前账号仍保持登录。' : reason instanceof Error ? reason.message : '账号切换失败，请重试。');
      setSwitching(false); setPassword('');
      requestAnimationFrame(() => passwordRef.current?.focus());
    }
  };

  return <dialog ref={dialogRef} className="account-switcher" aria-labelledby={headingId} onCancel={(event) => { if (switching) event.preventDefault(); else onClose(); }} onClose={() => { if (!switching) onClose(); }}>
    <header><div><span>LOCAL ACCOUNTS</span><h2 id={headingId}>切换账号</h2></div><button type="button" aria-label="关闭账号切换窗口" disabled={switching} onClick={onClose}>×</button></header>
    <p className="account-switcher-intro">选择本机账号并重新输入该账号密码。验证成功前，当前账号不会退出。</p>
    <form onSubmit={submit}>
      <div className="account-switch-list" aria-label="本机账号">
        {loading && <p className="account-switch-state" role="status">正在读取本机账号…</p>}
        {!loading && accounts.length === 0 && <p className="account-switch-state">本机暂未找到可切换账号。</p>}
        {accounts.map((account) => <button key={account.user_id} type="button" className={selectedId === account.user_id ? 'selected' : ''} aria-pressed={selectedId === account.user_id} disabled={switching} onClick={() => chooseAccount(account.user_id)}>
          <LocalAccountAvatar account={account} />
          <span><strong>{account.display_name}</strong><small>{account.identity_hint || account.user_id}</small></span>
          <i>{account.user_id === currentUserId ? '当前' : selectedId === account.user_id ? '✓' : '选择'}</i>
        </button>)}
      </div>
      {selectedId && <label className="account-switch-password"><span>账号密码</span><input ref={passwordRef} type="password" autoComplete="current-password" value={password} onChange={(event) => { setPassword(event.target.value); setError(''); }} disabled={switching} placeholder="请输入所选账号的密码" maxLength={128} required /></label>}
      {error && <p className="account-switch-error" role="alert">{error}</p>}
      <footer><button type="button" disabled={switching} onClick={onClose}>取消</button><button type="submit" className="account-switch-primary" disabled={!selectedId || !password || switching}>{switching ? '正在验证…' : '验证并切换'}</button></footer>
    </form>
  </dialog>;
}

export default function AccountMenu({ user, onUserUpdated, activeConversationId, busy, onOpenHistory, appearance, onAppearanceChange, preferenceNotice }: Props) {
  const panelId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const avatarTrigger = useRef<HTMLButtonElement>(null);
  const [editing, setEditing] = useState<'avatar' | 'nickname' | null>(null);
  const [exporting, setExporting] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [confirmingLogout, setConfirmingLogout] = useState(false);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const editProfile = (field: 'avatar' | 'nickname') => {
    panelRef.current?.hidePopover();
    setNotice(''); setError(''); setEditing(field);
  };

  const exportConversation = async () => {
    if (!activeConversationId || busy || exporting) return;
    setExporting(true); setNotice(''); setError('');
    try {
      const response = await apiFetch(`/api/agent/conversations/${encodeURIComponent(activeConversationId)}`, { cache: 'no-store' });
      if (!response.ok) throw new Error(await responseMessage(response, '无法导出问答，请稍后重试。'));
      const conversation: ExportConversation = await response.json();
      if (!Array.isArray(conversation.messages)) throw new Error('问答记录格式不完整，未生成导出文件。');
      const record = {
        product: 'LungSight', version, exported_at: new Date().toISOString(),
        notice: '科研与辅助信息整理记录，不构成诊断、处方或治疗建议。请妥善保管导出的问答资料。',
        conversation: {
          conversation_id: conversation.conversation_id, title: conversation.title,
          linked_task_id: conversation.linked_task_id, created_at: conversation.created_at,
          messages: conversation.messages.map((message: Record<string, unknown>) => ({
            role: message.role, content: message.content, created_at: message.created_at,
            citations: message.citations, support_level: message.support_level, risk_level: message.risk_level,
            provider: message.provider, model: message.model,
            input_tokens: message.input_tokens, output_tokens: message.output_tokens, total_tokens: message.total_tokens,
            response: message.response,
          })),
        },
      };
      const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `LungSight-问答记录-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('已发起当前问答记录下载，包含回答、引用和Token用量。');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '导出失败，请重试。'); }
    finally { setExporting(false); }
  };

  const signOut = async () => {
    if (busy || exporting || leaving) return;
    setLeaving(true); setError('');
    try {
      const response = await apiFetch('/api/auth/logout', { method: 'POST' });
      if (!response.ok && response.status !== 401) throw new Error(await responseMessage(response, '退出失败，请重试。'));
      window.location.replace('/auth');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法连接本地服务，请恢复连接后退出。');
      setLeaving(false);
    }
  };

  return <div className="account-menu">
    <button ref={avatarTrigger} type="button" className="account-avatar-trigger" popoverTarget={panelId} aria-label={`${user?.display_name || '用户'}的账户菜单`} title="账户与个性化" disabled={!user}>
      <UserAvatar user={user} />
    </button>
    <div ref={panelRef} id={panelId} popover="auto" className="account-popover" role="dialog" aria-label="账户与个性化">
      <header className="account-profile">
        <button type="button" className="account-profile-avatar account-edit-avatar" aria-label="更改头像" title="更改头像" disabled={!user || leaving} onClick={() => editProfile('avatar')}><UserAvatar user={user} /><span className="avatar-edit-mark">更换</span></button>
        <div><button type="button" className="account-edit-name" aria-label="更改昵称" title="更改昵称" disabled={!user || leaving} onClick={() => editProfile('nickname')}><strong>{user?.display_name}</strong><span aria-hidden="true">编辑</span></button><small>{user?.email || user?.phone_masked}</small><span>用户ID：{user?.user_id}</span></div>
        <button type="button" className="account-close" popoverTarget={panelId} popoverTargetAction="hide" aria-label="关闭账户菜单">×</button>
      </header>

      <section className="account-section" aria-label="个性化设置">
        <h2>个性化 <small>所有工作页面同步</small></h2>
        <div className="account-theme-options" role="group" aria-label="界面明暗">
          {themes.map((theme) => <button key={theme.id} type="button" aria-pressed={appearance.theme === theme.id} onClick={() => onAppearanceChange({ ...appearance, theme: theme.id })}>{theme.label}</button>)}
        </div>
        <div className="account-accent-options" role="group" aria-label="主题配色">
          {accents.map((accent) => <button key={accent.id} type="button" aria-pressed={appearance.accent === accent.id} onClick={() => onAppearanceChange({ ...appearance, accent: accent.id })}><i className={`accent-swatch ${accent.id}`} /><span><b>{accent.label}</b><small>{accent.detail}</small></span><em aria-hidden="true">{appearance.accent === accent.id ? '✓' : ''}</em></button>)}
        </div>
        <p className="account-hint" role="status">{preferenceNotice || '仅保存本机外观偏好，不影响医学影像与分析结果。'}</p>
      </section>

      <section className="account-section account-actions" aria-label="资料与支持">
        <DoctorProfileDetails key={user?.user_id} />
        <button type="button" className="account-history-action" onClick={() => { panelRef.current?.hidePopover(); onOpenHistory(); }}><span>历史问答库</span><i aria-hidden="true">↗</i></button>
        <button type="button" disabled={!activeConversationId || busy || exporting || leaving} onClick={() => void exportConversation()}><span>{exporting ? '正在导出…' : '导出当前问答'}</span><i aria-hidden="true">↓</i></button>
        <p className="account-hint">{busy ? '请等待当前操作完成后再导出或退出。' : !activeConversationId ? '从历史问答库选择对话后，可导出JSON记录。' : '只导出当前对话；下载文件可能含病例信息，请妥善保管。'}</p>
        <details><summary>帮助与反馈 <i aria-hidden="true">＋</i></summary><p>先配置模型API，再提问；查看引用可核对回答依据。CT上传和报告复核可从左侧进入。反馈问题时请记录操作步骤与错误提示，勿附个人身份信息或完整API Key。目前尚未接入在线反馈通道。</p></details>
        <details><summary>平台公告 <i aria-hidden="true">＋</i></summary><p>当前为测试版本，账号、问答记录和CT任务保存在本机后端。调用模型时会发送脱敏后的问题和检索上下文，不用于独立临床诊断。识别所需的API Key需要用户自行配置。</p></details>
        <details><summary>版本信息 <i aria-hidden="true">＋</i></summary><p>LungSight v{version} · 公共测试版本。</p></details>
        <details><summary>关于 LungSight <i aria-hidden="true">＋</i></summary><p>肺部CT科研与辅助信息工作台，整合影像模型、循证问答、医生复核和报告记录。AI输出仅供辅助参考，须由医生结合完整资料判断。</p></details>
        <details className="account-contact"><summary>联系我们 <i aria-hidden="true">＋</i></summary><div className="account-contact-body"><span>联系邮箱</span><a href="mailto:2934935729@qq.com">2934935729@qq.com</a><footer aria-label="QIONX Exploration Technologies"><strong><span className="qionx-main">QION</span><span className="qionx-x">X</span></strong><small>EXPLORATION TECHNOLOGIES</small></footer></div></details>
      </section>

      <section className="account-section account-actions account-session" aria-label="账号操作">
        <h2>账号</h2>
        <button type="button" disabled={busy || exporting || leaving || !user} onClick={() => { panelRef.current?.hidePopover(); setSwitcherOpen(true); }}><span>切换账号</span><i aria-hidden="true">⇄</i></button>
        <button type="button" className="account-logout" disabled={busy || exporting || leaving || !user} onClick={() => { panelRef.current?.hidePopover(); setError(''); setConfirmingLogout(true); }}>退出登录</button>
        <p className="account-hint">切换账号将退出当前会话并返回登录页。</p>
      </section>
      {notice && <p className="account-feedback" role="status">{notice}</p>}
      {error && <p className="account-feedback error" role="alert">{error}</p>}
    </div>
    {switcherOpen && user && <AccountSwitcher currentUserId={user.user_id} onClose={() => { setSwitcherOpen(false); requestAnimationFrame(() => avatarTrigger.current?.focus()); }} />}
    {confirmingLogout && <LogoutConfirm leaving={leaving} error={error} onCancel={() => { if (leaving) return; setConfirmingLogout(false); setError(''); requestAnimationFrame(() => avatarTrigger.current?.focus()); }} onConfirm={() => void signOut()} />}
    {editing && user && <ProfileEditor key={editing} field={editing} user={user} onSaved={(updated) => { onUserUpdated(updated); setNotice(editing === 'avatar' ? '头像已保存到账户。' : '昵称已保存到账户。'); }} onClose={() => { setEditing(null); avatarTrigger.current?.focus(); }} />}
  </div>;
}
