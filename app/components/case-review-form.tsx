'use client';

import { useEffect, useState } from 'react';
import { apiFetch, responseMessage } from '../auth-client';

export type Review = { reviewer_name: string; decision: string; corrected_class_cn: string | null; comment: string; reviewed_at: string };
const classes = { adenocarcinoma: '腺癌', large_cell_carcinoma: '大细胞癌', normal: '正常肺部', squamous_cell_carcinoma: '鳞状细胞癌' };
export default function CaseReviewForm({ taskId, review, onSaved }: { taskId: string; review: Review | null; onSaved: () => void }) {
  const [name, setName] = useState('');
  const [decision, setDecision] = useState('UNDETERMINED');
  const [correctedClass, setCorrectedClass] = useState('');
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void apiFetch('/api/auth/me', { signal: controller.signal }).then(async response => {
      if (response.ok) { const payload = await response.json() as { user?: { display_name?: string } }; if (!controller.signal.aborted) setName(payload.user?.display_name || ''); }
    }).catch(() => {});
    return () => controller.abort();
  }, []);
  if (review) return <section className="case-review-summary"><h3>已保存复核</h3><b>{review.decision === 'UNDETERMINED' ? '无法判断' : review.decision === 'CORRECT' ? `修正为：${review.corrected_class_cn}` : '确认研究模型排序'}</b><p>{review.comment || '未填写备注'}</p><small>{review.reviewer_name} · {new Date(review.reviewed_at).toLocaleString('zh-CN')} · 该复核已锁定</small></section>;
  return <form className="case-review-form" onSubmit={async event => {
    event.preventDefault(); if (saving) return; setSaving(true); setError('');
    try {
      const response = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, reviewer_name: name.trim(), corrected_class: decision === 'CORRECT' ? correctedClass : null, comment: comment.trim() }) });
      if (!response.ok) throw new Error(await responseMessage(response, '复核保存失败，输入已保留'));
      onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '复核保存失败'); }
    finally { setSaving(false); }
  }}><h3>当前切片复核</h3><label>复核意见<select value={decision} disabled={saving} onChange={event => setDecision(event.target.value)}><option value="UNDETERMINED">无法判断 / 需要进一步核对</option><option value="CONFIRM">确认研究模型排序</option><option value="CORRECT">修正研究分类</option></select></label>
    {decision === 'CORRECT' && <label>修正分类<select required value={correctedClass} disabled={saving} onChange={event => setCorrectedClass(event.target.value)}><option value="" disabled>请选择分类</option>{Object.entries(classes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
    <label>复核人<input required maxLength={80} value={name} disabled={saving} onChange={event => setName(event.target.value)} /></label><label>复核备注<textarea maxLength={1000} value={comment} disabled={saving} onChange={event => setComment(event.target.value)} placeholder="记录判断依据、分歧或待核对事项，请勿填写身份信息" /></label><small>保存后锁定本次复核。人工意见会与模型原始输出分别保留，不改变模型的研究用途边界。</small>{error && <p className="workbench-error" role="alert">{error}</p>}<button type="submit" disabled={saving || !name.trim() || (decision === 'CORRECT' && !correctedClass)}>{saving ? '保存中…' : '保存并锁定复核'}</button>
  </form>;
}
