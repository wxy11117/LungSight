'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { apiFetch, responseMessage, safeReturnTo } from '../auth-client';
import catalog from '../../config/registration-catalog.json';
import { accountIdentity, emptyRegistration, registrationError, registrationPayload } from './registration-form';
import type { AccountMethod, RegistrationDraft } from './registration-form';
import './registration.css';
import AuthLoginPanel from './AuthLoginPanel';

type Mode = 'login' | 'register';
const steps = ['医院信息', '医生资料', '账号安全'];

export default function AuthPage() {
  const [mode, setMode] = useState<Mode>('login');
  const [method, setMethod] = useState<AccountMethod>('phone');
  const [draft, setDraft] = useState<RegistrationDraft>({ ...emptyRegistration });
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [serviceOffline, setServiceOffline] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [search, setSearch] = useState('');
  const formRef = useRef<HTMLFormElement>(null);
  const returnTo = useRef('/agent');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    returnTo.current = safeReturnTo(params.get('returnTo'));
    const inspectRegistration = params.get('mode') === 'register';
    const frame = requestAnimationFrame(() => { if (inspectRegistration) setMode('register'); });
    let cancelled = false;
    void apiFetch('/api/auth/me', { cache: 'no-store' }).then((response) => {
      if (cancelled) return;
      setServiceOffline(response.status >= 500);
      if (response.ok) {
        if (inspectRegistration) setSignedIn(true);
        else window.location.replace(returnTo.current);
      }
    }).catch(() => { if (!cancelled) setServiceOffline(true); });
    return () => { cancelled = true; cancelAnimationFrame(frame); };
  }, []);

  const update = <K extends keyof RegistrationDraft>(key: K, value: RegistrationDraft[K]) => setDraft((previous) => ({ ...previous, [key]: value }));
  const switchMode = (next: Mode) => {
    if (submitting) return;
    setMode(next); setError('');
    setDraft((previous) => ({ ...previous, password: '', confirm_password: '' }));
  };
  const changeMethod = (next: AccountMethod) => {
    setMethod(next); setError('');
    setDraft((previous) => ({ ...previous, password: '', confirm_password: '' }));
  };
  const changeStep = (next: number) => {
    setStep(next); setError('');
    requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>('input, select')?.focus());
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setError('');
    if (mode === 'register') {
      const issue = registrationError(draft, method, step);
      if (issue) { setStep(issue.step); setError(issue.message); return; }
      if (step < 2) { changeStep(step + 1); return; }
    }
    setSubmitting(true);
    try {
      const response = await apiFetch('/api/auth/' + mode, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mode === 'login' ? { ...accountIdentity(method, draft), password: draft.password } : registrationPayload(draft, method)),
      });
      setServiceOffline(response.status >= 500);
      if (!response.ok) throw new Error(await responseMessage(response, mode === 'login' ? '登录失败' : '注册失败'));
      setDraft((previous) => ({ ...previous, password: '', confirm_password: '' }));
      window.location.replace(returnTo.current);
    } catch (reason) {
      if (reason instanceof TypeError) setServiceOffline(true);
      setError(reason instanceof TypeError ? '无法连接本地服务，请恢复服务后重试。' : reason instanceof Error ? reason.message : '认证服务暂时不可用');
    } finally { setSubmitting(false); }
  };

  const visibleHospitals = catalog.hospitals.filter((hospital) => hospital.province === draft.province && hospital.name.includes(search.trim()));
  const chooseProvince = (province: string) => {
    setDraft((previous) => ({ ...previous, province, city: ['北京市', '天津市', '上海市', '重庆市', '香港特别行政区', '澳门特别行政区'].includes(province) ? province : '', hospital_id: '', hospital_name: '' }));
    setSearch('');
  };
  const chooseHospital = (id: string) => {
    const hospital = catalog.hospitals.find((item) => item.id === id);
    setDraft((previous) => ({ ...previous, hospital_id: hospital?.id || '', hospital_name: hospital?.name || '', city: hospital?.city || previous.city }));
  };

  const accountFields = <>
    <div className="auth-identity-tabs" role="group" aria-label={mode === 'login' ? '登录方式' : '注册方式'}>
      <button type="button" aria-pressed={method === 'phone'} onClick={() => changeMethod('phone')}>手机号{mode === 'login' ? '登录' : '注册'}</button>
      <button type="button" aria-pressed={method === 'email'} onClick={() => changeMethod('email')}>邮箱{mode === 'login' ? '登录' : '注册'}</button>
    </div>
    {method === 'phone' ? <label><span>手机号 *</span><div className="auth-phone-field">
      <select aria-label="手机号区号" value={draft.calling_code} onChange={(event) => update('calling_code', event.target.value)}>
        <option value="+86">+86 中国大陆</option><option value="+852">+852 中国香港</option><option value="+853">+853 中国澳门</option><option value="+886">+886 中国台湾</option>
      </select>
      <input type="tel" aria-label="手机号" inputMode="tel" autoComplete="tel-national" value={draft.phone} onChange={(event) => update('phone', event.target.value)} placeholder={draft.calling_code === '+86' ? '请输入11位手机号' : '手机号，不含区号及首位0'} minLength={8} maxLength={20} required />
    </div></label> : <label><span>电子邮箱 *</span><input type="email" autoComplete="username" value={draft.email} onChange={(event) => update('email', event.target.value)} placeholder="name@example.com" maxLength={254} required /></label>}
    <label><span>账号密码 *</span><input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={draft.password} onChange={(event) => update('password', event.target.value)} placeholder={mode === 'login' ? '输入账号密码' : '10–128位，包含字母和数字'} minLength={mode === 'login' ? 1 : 10} maxLength={128} required /></label>
    {mode === 'register' && <label><span>确认密码 *</span><input type="password" autoComplete="new-password" value={draft.confirm_password} onChange={(event) => update('confirm_password', event.target.value)} placeholder="再次输入账号密码" minLength={10} maxLength={128} required /></label>}
  </>;

  // 原有注册表单保留在父页面；登录区使用无框架的独立 HTML 面板。
  const showRegistration = Boolean(mode === 'register');
  return <main className="auth-shell registration-shell">
    <section className="auth-story">
      <Link href="/" className="auth-brand"><span className="brand-mark" /><span><b>LungSight</b><small>MEDICAL INTELLIGENCE AGENT</small></span></Link>
      <div className="auth-story-copy">
        <span>YOUR CLINICAL WORKSPACE</span>
        <h1>连接医学知识，<br />开启个人工作台。</h1>
        <p>从医院与医生资料开始，建立你的 LungSight 账号。使用手机号或邮箱登录，继续影像分析与医学问答。</p>
        <div className="auth-feature-list">
          <article><i>01</i><div><strong>医学 AI 问答</strong><small>围绕医学问题展开对话，结合资料库与病例上下文提供参考。</small></div></article>
          <article><i>02</i><div><strong>肺部 CT 辅助分析</strong><small>上传肺部 CT 影像，查看五折模型分析、质量提示与模型关注区域。</small></div></article>
          <article><i>03</i><div><strong>病例复核与报告</strong><small>集中管理历史病例，记录复核意见，查看并导出结构化报告。</small></div></article>
        </div>
      </div>
      <footer>仅用于科研与辅助信息分析，不构成临床诊断。</footer>
    </section>
    <section className="auth-panel">
      {!showRegistration && <AuthLoginPanel onRegister={() => switchMode('register')} returnTo={returnTo} />}
      {showRegistration && <div className="auth-card">
        <div className="auth-tabs" role="group" aria-label="账号操作">
          <button type="button" disabled={submitting} aria-pressed={mode === 'login'} className={mode === 'login' ? 'active' : ''} onClick={() => switchMode('login')}>登录账号</button>
          <button type="button" disabled={submitting} aria-pressed={mode === 'register'} className={mode === 'register' ? 'active' : ''} onClick={() => switchMode('register')}>首次注册</button>
        </div>
        <div className="auth-card-title"><span>{mode === 'login' ? 'WELCOME BACK' : 'CREATE ACCOUNT · 0' + (step + 1) + ' / 03'}</span><h2>{mode === 'login' ? '登录 LungSight' : steps[step]}</h2><p>{mode === 'login' ? '使用注册时的手机号或邮箱及密码登录。原有邮箱账号仍可使用。' : '标有 * 的为必填项，所填资料仅用于本地账号档案。'}</p></div>
        {mode === 'register' && <ol className="registration-steps" aria-label="注册进度">{steps.map((label, index) => <li key={label} aria-current={index === step ? 'step' : undefined} className={index <= step ? 'reached' : ''}><b>{index + 1}</b><span>{label}</span></li>)}</ol>}
        {signedIn && <div className="auth-notice warning">当前已有登录会话，注册成功后将切换到新账号。<a href="/agent">返回当前工作区</a></div>}
        {serviceOffline && <div className="auth-notice warning" role="status">本地服务暂未连接，请启动服务后重试。</div>}
        {error && <div className="auth-notice error" role="alert">{error}</div>}
        <form ref={formRef} onSubmit={submit} className="auth-form" aria-busy={submitting}>
          <fieldset disabled={submitting} className="registration-fields">
            {mode === 'register' && step === 0 && <>
              <label><span>所在省 / 自治区 / 直辖市 / 特别行政区 *</span><select value={draft.province} onChange={(event) => chooseProvince(event.target.value)} required><option value="">请选择省级地区</option>{catalog.provinces.map((province) => <option key={province}>{province}</option>)}</select></label>
              <label><span>查找已收录医院</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="输入医院名称关键词（可选）" disabled={!draft.province} maxLength={120} /></label>
              <label><span>选择医院或手动填写 *</span><select value={draft.hospital_id} onChange={(event) => chooseHospital(event.target.value)} disabled={!draft.province}><option value="">未找到 / 手动填写医院全称</option>{visibleHospitals.map((hospital) => <option key={hospital.id} value={hospital.id}>{hospital.name}</option>)}{draft.hospital_id && !visibleHospitals.some((h) => h.id === draft.hospital_id) && <option value={draft.hospital_id}>{draft.hospital_name}（已选）</option>}</select></label>
              <div className="registration-grid"><label><span>城市 / 地区 *</span><input value={draft.city} onChange={(event) => update('city', event.target.value)} autoComplete="address-level2" placeholder="例如：成都市" minLength={2} maxLength={60} required readOnly={!!draft.hospital_id} /></label><label><span>医院全称 *</span><input value={draft.hospital_name} onChange={(event) => update('hospital_name', event.target.value)} autoComplete="organization" placeholder="请填写实际执业医院全称" minLength={2} maxLength={120} required readOnly={!!draft.hospital_id} /></label></div>
              <p className="registration-hint">{catalog.directory_notice}</p>
            </>}
            {mode === 'register' && step === 1 && <>
              <div className="registration-summary"><strong>{draft.hospital_name}</strong><small>{draft.province} · {draft.city}</small></div>
              <label><span>医生姓名 *</span><input value={draft.real_name} onChange={(event) => update('real_name', event.target.value)} autoComplete="name" placeholder="填写医生姓名，与昵称分别保存" minLength={2} maxLength={60} required /></label>
              <label><span>所在科室 *</span><input list="registration-departments" value={draft.department} onChange={(event) => update('department', event.target.value)} placeholder="选择常见科室或输入实际科室" minLength={2} maxLength={60} required /><datalist id="registration-departments">{catalog.departments.map((department) => <option key={department} value={department} />)}</datalist></label>
              <label><span>医生职称 / 培训阶段 *</span><select value={draft.professional_title} onChange={(event) => update('professional_title', event.target.value)} required><option value="">请选择</option>{catalog.professional_titles.map((title) => <option key={title}>{title}</option>)}</select></label>
              <p className="registration-hint">以上为用户自填资料，尚未核验执业资质，不授予任何管理权限。此阶段不收集身份证、执业证照片或患者信息。</p>
            </>}
            {(mode === 'login' || step === 2) && <>
              {mode === 'register' && <label><span>账号昵称 *</span><input autoComplete="nickname" value={draft.display_name} onChange={(event) => update('display_name', event.target.value)} placeholder="用于头像菜单与个人工作区" minLength={2} maxLength={60} required /></label>}
              {accountFields}
              {mode === 'register' && <>
                <p className="registration-hint">任选一种方式即可注册，无需同时提供手机号和邮箱。目前未接入短信或邮件验证，注册不代表联系方式或医生身份已认证。请使用本人联系方式。</p>
                <details className="registration-privacy"><summary>阅读用户协议与隐私说明</summary><p>本地科研原型，仅供辅助信息分析。AI 结果需要专业复核，不能替代临床诊断。</p><p>医院、医生资料、联系方式和账号记录保存在本机后端。密码只保存哈希，确认密码不保存；注册资料不会作为聊天上下文发送给大模型。问答功能仍会按其规则发送脱敏问题与相关证据。</p><p>请妥善保管本机及备份。当前尚无在线身份认证、短信 / 邮件验证码或自助找回密码服务。后续联网账号服务启用前，需要另行说明数据用途与处理方式。</p></details>
                <div className="auth-consents"><label><input type="checkbox" checked={draft.accepted_terms} onChange={(event) => update('accepted_terms', event.target.checked)} required /><span>我已阅读并同意上述用户协议，理解辅助分析的使用范围</span></label><label><input type="checkbox" checked={draft.accepted_privacy} onChange={(event) => update('accepted_privacy', event.target.checked)} required /><span>我已阅读隐私说明，同意保存填写的账号与医生资料</span></label></div>
              </>}
            </>}
            <div className="registration-actions">{mode === 'register' && step > 0 && <button type="button" className="registration-back" onClick={() => changeStep(step - 1)}>← 上一步</button>}<button type="submit" className="auth-submit">{submitting ? '正在处理…' : mode === 'login' ? '登录工作区 →' : step < 2 ? '下一步 →' : '完成注册并进入 →'}</button></div>
          </fieldset>
        </form>
        <p className="auth-switch">{mode === 'login' ? '第一次使用？' : '已经有账号？'} <button type="button" disabled={submitting} onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}>{mode === 'login' ? '创建医生账号' : '返回登录'}</button></p>
      </div>}
    </section>
  </main>;
}
