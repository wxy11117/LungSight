'use client';

import { useState } from 'react';
import { apiFetch, responseMessage } from '../auth-client';

type DoctorProfile = {
  real_name: string; province: string; city: string; hospital_name: string;
  department: string; professional_title: string; verification_status: 'SELF_DECLARED';
};

export default function DoctorProfileDetails() {
  const [profile, setProfile] = useState<DoctorProfile | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const load = async () => {
    if (loading) return;
    setLoading(true); setError('');
    try {
      const response = await apiFetch('/api/auth/doctor-profile', { cache: 'no-store' });
      if (!response.ok) throw new Error(await responseMessage(response, '医生资料暂时无法读取'));
      const result: { profile: DoctorProfile | null } = await response.json();
      setProfile(result.profile); setLoaded(true);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '读取失败'); }
    finally { setLoading(false); }
  };
  return <details onToggle={(event) => { if (event.currentTarget.open && !loaded) void load(); }}>
    <summary>医生资料 · 用户自填 <i aria-hidden="true">＋</i></summary>
    {loading && <p role="status">正在读取个人资料…</p>}
    {error && <><p role="alert">{error}</p><button type="button" onClick={() => void load()}>重新读取</button></>}
    {loaded && (profile ? <p>{profile.real_name} · {profile.professional_title}<br />{profile.hospital_name} · {profile.department}<br />{profile.province} · {profile.city}<br />资料由用户自行填写，未核验执业资质。手机号或邮箱也尚未经验证码验证。</p> : <p>此账号在新版注册流程前创建，暂无医生档案。原账号、对话与病例保持可用。</p>)}
  </details>;
}
