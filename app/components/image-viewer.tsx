'use client';

import { useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { apiFetch, responseMessage } from '../auth-client';
import { boundedPan, clamp, fitImage, imagePoint } from './viewer-geometry';

type PointNote = { id: string; x: number; y: number; note: string };
type AnnotationDocument = { revision: number; items: PointNote[] };
type Props = { src: string; attentionSrc?: string; taskId?: string; title: string; sliceIndex?: number; sliceCount?: number; onSliceChange?: (index: number) => void };

export default function ImageViewer(props: Props) {
  return <ViewerCanvas key={props.taskId || props.src} {...props} />;
}

function ViewerCanvas({ src, attentionSrc, taskId, title, sliceIndex = 0, sliceCount = 1, onSliceChange }: Props) {
  const stage = useRef<HTMLDivElement>(null);
  const plane = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const [viewport, setViewport] = useState({ width: 500, height: 440 });
  const [size, setSize] = useState({ width: 512, height: 512 });
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [brightness, setBrightness] = useState(100);
  const [contrast, setContrast] = useState(100);
  const [overlay, setOverlay] = useState(false);
  const [opacity, setOpacity] = useState(65);
  const [marking, setMarking] = useState(false);
  const [draft, setDraft] = useState<{ x: number; y: number } | null>(null);
  const [note, setNote] = useState('');
  const [annotations, setAnnotations] = useState<AnnotationDocument>({ revision: 0, items: [] });
  const [notesReady, setNotesReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [imageError, setImageError] = useState(false);
  const [imageReady, setImageReady] = useState(false);
  const [attentionError, setAttentionError] = useState(false);
  const fitted = fitImage(size.width, size.height, viewport.width, viewport.height);

  useEffect(() => {
    const node = stage.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setViewport({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    void apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/annotations`, { signal: controller.signal, cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error(await responseMessage(response, '人工标记读取失败'));
      const document = await response.json() as AnnotationDocument;
      if (!controller.signal.aborted) { setAnnotations(document); setNotesReady(true); }
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '人工标记读取失败'); });
    return () => controller.abort();
  }, [taskId]);

  const changeZoom = (value: number) => {
    const next = clamp(value, 1, 6);
    setZoom(next); setPan(current => boundedPan(current.x, current.y, fitted.width, fitted.height, next));
  };
  const reset = () => { setZoom(1); setPan({ x: 0, y: 0 }); setBrightness(100); setContrast(100); setOverlay(false); };
  const pointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || imageError || !imageReady || saving) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
  };
  const pointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current || marking) return;
    setPan(boundedPan(drag.current.panX + event.clientX - drag.current.x, drag.current.panY + event.clientY - drag.current.y, fitted.width, fitted.height, zoom));
  };
  const pointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current; drag.current = null;
    if (!marking || !start || !plane.current || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) return;
    const point = imagePoint(event.clientX, event.clientY, plane.current.getBoundingClientRect());
    if (point) { setDraft(point); setNote(''); }
  };
  const save = async (items: PointNote[]) => {
    if (!taskId || saving) return;
    setSaving(true); setError('');
    try {
      const response = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/annotations`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: annotations.revision, items }) });
      if (!response.ok) throw new Error(await responseMessage(response, '标记保存失败，当前输入已保留'));
      setAnnotations(await response.json() as AnnotationDocument); setDraft(null); setNote(''); setMarking(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '标记保存失败'); }
    finally { setSaving(false); }
  };

  return <section className="image-viewer" aria-label="交互式影像查看器">
    <header className="viewer-heading"><div><span>影像查看</span><strong>{title}</strong></div><small>{Math.round(zoom * 100)}% · {size.width} × {size.height}</small></header>
    <div className="viewer-tools">
      <button type="button" aria-label="缩小影像" onClick={() => changeZoom(zoom - .25)} disabled={zoom === 1}>−</button>
      <button type="button" aria-label="放大影像" onClick={() => changeZoom(zoom + .25)} disabled={zoom === 6}>＋</button>
      <button type="button" onClick={reset}>重置视图</button>
      <button type="button" disabled={!attentionSrc || attentionError} aria-pressed={overlay} onClick={() => setOverlay(!overlay)}>Grad-CAM 叠加</button>
      {taskId && <button type="button" disabled={!notesReady || saving || annotations.items.length >= 50 || imageError || !imageReady} aria-pressed={marking} onClick={() => { setMarking(!marking); setDraft(null); }}>人工标记</button>}
    </div>
    <div className={`viewer-stage ${marking ? 'is-marking' : ''}`} ref={stage} tabIndex={0} role="region" aria-label="影像区域，拖动平移，左右键切片，加减键缩放，零键重置"
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={() => { drag.current = null; }}
      onKeyDown={event => {
        if (event.target !== event.currentTarget) return;
        if (['ArrowLeft', 'ArrowRight', '+', '=', '-', '0'].includes(event.key)) event.preventDefault();
        if (event.key === 'ArrowLeft') onSliceChange?.(Math.max(0, sliceIndex - 1));
        if (event.key === 'ArrowRight') onSliceChange?.(Math.min(sliceCount - 1, sliceIndex + 1));
        if (['+', '='].includes(event.key)) changeZoom(zoom + .25);
        if (event.key === '-') changeZoom(zoom - .25);
        if (event.key === '0') reset();
      }}>
      <div ref={plane} className="viewer-plane" style={{ width: fitted.width, height: fitted.height, transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}>
        <img src={src} alt={title} draggable={false} style={{ filter: `brightness(${brightness}%) contrast(${contrast}%)` }} onLoad={event => { setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight }); setImageError(false); setImageReady(true); }} onError={() => setImageError(true)} />
        {attentionSrc && overlay && <img className="viewer-attention" src={attentionSrc} alt="模型注意力可视化，非病灶分割" draggable={false} style={{ opacity: opacity / 100 }} onError={() => { setAttentionError(true); setOverlay(false); }} />}
        {!imageError && annotations.items.map((item, index) => <span className="viewer-marker" key={item.id} title={`人工标记 ${index + 1}：${item.note}`} style={{ left: `${item.x * 100}%`, top: `${item.y * 100}%`, transform: `translate(-50%, -50%) scale(${1 / zoom})` }}>{index + 1}</span>)}
        {draft && <span className="viewer-marker draft" style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, transform: `translate(-50%, -50%) scale(${1 / zoom})` }}>＋</span>}
      </div>
      {imageError && <div className="viewer-image-error" role="alert">影像加载失败，请检查本地服务或重新登录。</div>}
      <span className="viewer-hint">{marking ? '点击影像放置人工标记' : '拖动平移 · + / − 缩放 · ← / → 切片'}</span>
    </div>
    <div className="viewer-adjustments">
      <label>亮度 {brightness}%<input aria-label="显示亮度" type="range" min="40" max="180" value={brightness} onChange={event => setBrightness(Number(event.target.value))} /></label>
      <label>对比度 {contrast}%<input aria-label="显示对比度" type="range" min="50" max="250" value={contrast} onChange={event => setContrast(Number(event.target.value))} /></label>
      {overlay && <label>叠加 {opacity}%<input aria-label="注意力叠加透明度" type="range" min="0" max="100" value={opacity} onChange={event => setOpacity(Number(event.target.value))} /></label>}
    </div>
    {sliceCount > 1 && <div className="viewer-slices"><button type="button" disabled={sliceIndex === 0} onClick={() => onSliceChange?.(sliceIndex - 1)}>上一张</button><label>已分析切片 {sliceIndex + 1} / {sliceCount}<input aria-label="切片位置" type="range" min="0" max={sliceCount - 1} value={sliceIndex} onChange={event => onSliceChange?.(Number(event.target.value))} /></label><button type="button" disabled={sliceIndex >= sliceCount - 1} onClick={() => onSliceChange?.(sliceIndex + 1)}>下一张</button></div>}
    <p className="viewer-scope">调节仅影响显示，不改变推理输入。亮度与对比度不是原始 DICOM 的 HU 窗宽窗位；此处浏览已保存的分析切片。</p>
    {attentionError && <p role="alert">注意力图未能加载，原图仍可查看。</p>}
    {draft && <div className="viewer-note-editor"><label>人工备注（切换切片前请先保存；请勿填写身份信息）<textarea autoFocus maxLength={500} value={note} onChange={event => setNote(event.target.value)} placeholder="记录此位置需要查看或讨论的内容" /></label><button type="button" disabled={saving || !note.trim()} onClick={() => void save([...annotations.items, { ...draft, id: crypto.randomUUID(), note: note.trim() }])}>{saving ? '保存中…' : '保存标记'}</button><button type="button" disabled={saving} onClick={() => setDraft(null)}>取消标记</button></div>}
    {error && <p className="workbench-error" role="alert">{error}</p>}
    {!!annotations.items.length && <ol className="viewer-notes">{annotations.items.map((item, index) => <li key={item.id}><b>人工标记 {index + 1}</b><p>{item.note}</p><a href={`/agent?task=${encodeURIComponent(taskId || '')}&focus=${encodeURIComponent(`人工标记 ${index + 1}：${item.note}。这是用户备注，并非已验证的影像发现。请说明需要核对的资料和局限。`)}`}>带入当前影像问答</a><button type="button" disabled={saving} onClick={() => void save(annotations.items.filter(point => point.id !== item.id))}>移除标记</button></li>)}</ol>}
  </section>;
}
