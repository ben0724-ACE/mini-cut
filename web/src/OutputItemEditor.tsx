import { useState, type ReactNode } from "react";
import type { HighlightClip } from "./api";

type Changes = {deleted?: boolean; display_text?: string; source_start_ms?: number; source_end_ms?: number};
export function OutputItemEditor({clip, busy, onSave, onJump, actions}: {clip: HighlightClip; busy: boolean; onSave: (changes: Changes) => Promise<void>; onJump: (seconds?:number) => void; actions?:ReactNode}) {
  const [draft, setDraft] = useState(clip.text);
  const [start, setStart] = useState(clip.start_ms / 1000);
  const [end, setEnd] = useState(clip.end_ms / 1000);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  async function save(changes: Changes) {
    setError(""); setMessage("");
    try {await onSave(changes); setMessage(changes.display_text !== undefined ? "字幕已保存" : changes.source_start_ms !== undefined ? "范围已保存，字幕已按新范围更新" : "片段状态已保存（未保存字幕草稿）");}
    catch (reason: unknown) {setError(reason instanceof Error ? reason.message : "保存失败");}
  }
  const valid = Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end > start;
  return <li className={clip.deleted ? "segment segment--delete" : "segment"}>
    <p>{clip.role === "hook" ? "开场预告" : "正文"} · {clip.deleted ? "已删除" : `${((clip.end_ms-clip.start_ms)/1000).toFixed(2)} 秒`}</p>
    <div className="clip-boundaries">
      <label>开始（源视频秒）<input aria-label={`开始 ${clip.instance_id}`} type="number" min="0" step="0.1" value={start} disabled={busy} onChange={event=>setStart(Number(event.target.value))} /></label>
      <label>结束（源视频秒）<input aria-label={`结束 ${clip.instance_id}`} type="number" min="0" step="0.1" value={end} disabled={busy} onChange={event=>setEnd(Number(event.target.value))} /></label>
    </div>
    <button disabled={busy} onClick={()=>setStart(Math.max(0,Math.round((start-0.5)*1000)/1000))}>向前补 0.5 秒</button>
    <button disabled={busy} onClick={()=>setEnd(Math.round((end+0.5)*1000)/1000)}>向后补 0.5 秒</button>
    <button disabled={!valid} onClick={()=>onJump(start)}>跳转 {start.toFixed(2)} 秒</button>
    <button disabled={busy||!valid} onClick={()=>void save({source_start_ms:Math.round(start*1000),source_end_ms:Math.round(end*1000)})}>保存范围</button>
    <p className="helper-text">先听源视频再调范围；保存范围会重新提取字幕，请之后再校正文字。</p>
    <label>显示字幕<textarea aria-label={`字幕 ${clip.instance_id}`} value={draft} disabled={busy} maxLength={2000} onChange={event=>{setDraft(event.target.value);setMessage("");}} /></label>
    <button disabled={busy||!draft.trim()} onClick={()=>void save({display_text:draft.trim()})}>保存字幕</button>
    <button disabled={busy} onClick={()=>void save({deleted:!clip.deleted})}>{clip.deleted ? "恢复片段" : "删除片段"}</button>
    {actions}{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  </li>;
}
