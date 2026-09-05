export const apiBaseUrl = process.env.NEXT_PUBLIC_LUNGSIGHT_API_URL ?? 'http://127.0.0.1:8001';

export type AuthUser = {
  user_id: string;
  email: string | null;
  phone_masked?: string | null;
  identity_verification?: 'UNVERIFIED';
  display_name: string;
  status: string;
  created_at: string;
  last_login_at: string | null;
  avatar_url?: string | null;
  session_expires_at?: string;
};

export function apiFetch(path: string, init: RequestInit = {}) {
  return fetch(`${apiBaseUrl}${path}`, {
    ...init,
    credentials: 'include',
  });
}

export async function responseMessage(response: Response, fallback: string) {
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  return typeof payload?.detail === 'string' ? payload.detail : fallback;
}

export function safeReturnTo(value: string | null, fallback = '/agent') {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return fallback;
  return value;
}
