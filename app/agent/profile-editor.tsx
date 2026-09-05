'use client';

import { useEffect, useId, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { apiBaseUrl, apiFetch, responseMessage } from '../auth-client';
import type { AuthUser } from '../auth-client';

export function UserAvatar({ user }: { user: AuthUser | null }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const avatarUrl = user?.avatar_url;
  if (avatarUrl && failedUrl !== avatarUrl) {
    // A protected local image needs the browser's session cookie, not an image proxy.
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={`${apiBaseUrl}${avatarUrl}`} alt="" onError={() => setFailedUrl(avatarUrl)} />;
  }
  return <>{Array.from(user?.display_name.trim() || 'U')[0].toLocaleUpperCase()}</>;
}

type Props = {
  user: AuthUser;
  field: 'avatar' | 'nickname';
  onSaved: (user: AuthUser) => void;
  onClose: () => void;
};

export default function ProfileEditor({ user, field, onSaved, onClose }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const chooseRef = useRef<HTMLButtonElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const previewRef = useRef<string | null>(null);
  const headingId = useId();
  const nameInputId = useId();
  const [confirmed, setConfirmed] = useState(false);
  const [nickname, setNickname] = useState(user.display_name);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [imageReady, setImageReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const isAvatar = field === 'avatar';
  const cleanName = nickname.trim();
  const nameLength = Array.from(cleanName).length;
  const validName = nameLength >= 2 && nameLength <= 60 && !/[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\u2028\u2029]/u.test(cleanName);
  const canSave = isAvatar ? !!file && imageReady : validName && cleanName !== user.display_name;

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    };
  }, []);

  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0];
    event.target.value = '';
    if (!selected) return;
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    previewRef.current = null;
    setFile(null); setPreview(null); setImageReady(false); setError('');
    if (!selected.size || selected.size > 3 * 1024 * 1024) {
      setError('请选择非空、且不超过3MB的图片。'); return;
    }
    if (selected.type && !['image/png', 'image/jpeg', 'image/webp'].includes(selected.type)) {
      setError('仅支持PNG、JPEG或WebP静态图片。'); return;
    }
    const url = URL.createObjectURL(selected);
    previewRef.current = url; setPreview(url); setFile(selected);
  };

  const saveProfile = async (event: FormEvent) => {
    event.preventDefault();
    if (!confirmed || !canSave || saving) return;
    setSaving(true); setError('');
    try {
      let response: Response;
      if (isAvatar && file) {
        const body = new FormData(); body.append('file', file);
        response = await apiFetch('/api/auth/avatar', { method: 'POST', body, signal: AbortSignal.timeout(20000) });
      } else {
        response = await apiFetch('/api/auth/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ display_name: cleanName }), signal: AbortSignal.timeout(20000) });
      }
      if (!response.ok) throw new Error(await responseMessage(response, '保存失败，请检查内容后重试。'));
      const result: { user: AuthUser } = await response.json();
      onSaved(result.user);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error && !['TimeoutError', 'AbortError', 'TypeError'].includes(reason.name) ? reason.message : '连接中断或超时，请刷新核对是否已保存后重试。');
      setSaving(false);
    }
  };

  return <dialog ref={dialogRef} className="profile-editor" aria-labelledby={headingId} onCancel={(event) => { if (saving) event.preventDefault(); else onClose(); }} onClose={onClose}>
    <header><span>个人资料 · {confirmed ? '编辑' : '确认'}</span><button type="button" aria-label="关闭个人资料窗口" disabled={saving} onClick={onClose}>×</button></header>
    <h2 id={headingId}>{confirmed ? (isAvatar ? '上传新头像' : '编辑昵称') : (isAvatar ? '是否更改头像？' : '是否更改昵称？')}</h2>
    {!confirmed ? <>
      <p>确认后将打开{isAvatar ? '头像上传窗口，你可以选择图片并预览' : '昵称编辑窗口'}。只有点击保存后才会修改账户资料。</p>
      <footer><button type="button" onClick={onClose}>取消</button><button type="button" className="profile-primary" onClick={() => { setConfirmed(true); requestAnimationFrame(() => (isAvatar ? chooseRef.current : nameRef.current)?.focus()); }}>确认更改</button></footer>
    </> : <form onSubmit={saveProfile}>
      {isAvatar ? <>
        <div className="profile-avatar-preview">
          {preview ?
            // A user-selected local blob is previewed directly; it is not sent anywhere before Save.
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt="新头像预览" onLoad={(event) => {
              const image = event.currentTarget;
              if (Math.max(image.naturalWidth, image.naturalHeight) > 4096 || image.naturalWidth * image.naturalHeight > 16_000_000) { setError('图片边长不能超过4096像素，且总像素不能超过1600万。'); setImageReady(false); }
              else setImageReady(true);
            }} onError={() => { setImageReady(false); setError('无法预览此图片，请重新选择。'); }} />
            : <UserAvatar user={user} />}
        </div>
        <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" aria-label="选择头像图片" hidden disabled={saving} onChange={selectFile} />
        <button ref={chooseRef} type="button" className="profile-choose-file" disabled={saving} onClick={() => fileInput.current?.click()}>{file ? '重新选择图片' : '选择头像图片'}</button>
        {file && <p className="profile-file-name">{file.name}</p>}
        <p className="profile-note">支持PNG、JPEG、WebP静态图片，最大3MB。保存时居中裁剪为256×256像素，并清除图片附带的元数据。</p>
      </> : <>
        <label htmlFor={nameInputId}>新昵称</label>
        <input ref={nameRef} id={nameInputId} value={nickname} onChange={(event) => { setNickname(event.target.value); setError(''); }} disabled={saving} autoComplete="off" placeholder="请输入2至60个字符" aria-describedby={`${nameInputId}-help`} />
        <p id={`${nameInputId}-help`} className="profile-note">{nameLength}/60 个字符 · 不支持换行或不可见控制字符。昵称修改不会改变登录邮箱和用户ID。</p>
      </>}
      {error && <p className="profile-error" role="alert">{error}</p>}
      <footer><button type="button" disabled={saving} onClick={onClose}>取消</button><button type="submit" className="profile-primary" disabled={!canSave || saving}>{saving ? '正在保存…' : isAvatar ? '保存头像' : '保存昵称'}</button></footer>
    </form>}
  </dialog>;
}
