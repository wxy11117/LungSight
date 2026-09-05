'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from './auth-client';

export default function AgentAuthGuard({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<'checking' | 'allowed'>('checking');

  useEffect(() => {
    let active = true;
    void apiFetch('/api/auth/me', { cache: 'no-store' }).then((response) => {
      if (!active) return;
      if (response.ok) {
        setState('allowed');
        return;
      }
      const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      window.location.replace(`/auth?returnTo=${encodeURIComponent(returnTo)}`);
    }).catch(() => {
      if (active) window.location.replace('/auth?service=offline');
    });
    return () => { active = false; };
  }, []);

  if (state !== 'allowed') {
    return <main className="auth-checking"><span className="brand-mark" /><p>正在验证安全会话…</p></main>;
  }
  return children;
}
