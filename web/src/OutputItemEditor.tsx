import { useState, type ReactNode } from "react";
import type { HighlightClip } from "./api";

type Changes = {deleted?: boolean; display_text?: string; source_start_ms?: number; source_end_ms?: number};
export function OutputItemEditor({clip, busy, onSave, onJump, actions, range, onRange, onAudition, durationMs}: {clip: HighlightClip; busy: boolean; onSave: (changes: Changes) => Promise<void>; onJump: (seconds?:number) => void; actions?:ReactNode;range?:{start:number;end:number};onRange?:(start:number,end:number)=>void;onAudition?:(part:"start"|"end"|"whole")=>void;durationMs?:number}) {
  const [draft, setDraft] = useState(clip.text);
  const [localStart, setStart] = useState(clip.start_ms / 1000);
  const [localEnd, setEnd] = useState(clip.end_ms / 1000);
  const start=range?range.start/1000:localStart;const end=range?range.end/1000:localEnd;
  const [step,setStep]=useState(0.5);const [full,setFull]=useState(false);
  const limit=(durationMs??Math.max(clip.end_ms+10000,end*1000))/1000;
  function change(a:number,b:number){if(onRange)onRange(Math.round(a*1000),Math.round(b*1000));else{setStart(a);setEnd(b);}}
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  async function save(changes: Changes) {
    setError(""); setMessage("");
    try {await onSave(changes); setMessage(changes.display_text !== undefined ? "字幕已保存" : changes.source_start_ms !== undefined ? "范围已保存，字幕已按新范围更新" : "片段状态已保存（未保存字幕草稿）");}
    catch (reason: unknown) {setError(reason instanceof Error ? reason.message : "保存失败");}
  }
  const valid = Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end > start && end <= limit;
  return <li className={clip.deleted ? "segment segment--delete" : "segment"}>
    <p>{clip.role === "hook" ? "开场预告" : "正文"} · {clip.deleted ? "已删除" : `${(end-start).toFixed(2)} 秒`}</p>
    <div className="clip-boundaries">
      <label>开始（源视频秒）<input aria-label={`开始 ${clip.instance_id}`} type="number" min="0" step="0.1" value={start} disabled={busy} onChange={event=>change(Number(event.target.value),end)} /></label>
      <label>结束（源视频秒）<input aria-label={`结束 ${clip.instance_id}`} type="number" min="0" step="0.1" value={end} disabled={busy} onChange={event=>change(start,Number(event.target.value))} /></label>
    </div>
    <label>调整步长<select aria-label={`步长 ${clip.instance_id}`} value={step} onChange={e=>setStep(Number(e.target.value))}><option value={0.1}>0.1 秒</option><option value={0.5}>0.5 秒</option><option value={1}>1 秒</option></select></label>
    <div className="boundary-actions"><button disabled={busy} onClick={()=>change(Math.max(0,start-step),end)}>开始 −</button><button disabled={busy} onClick={()=>change(Math.min(end-0.001,start+step),end)}>开始 ＋</button><button disabled={busy} onClick={()=>change(start,Math.max(start+0.001,end-step))}>结束 −</button><button disabled={busy} onClick={()=>change(start,Math.min(limit,end+step))}>结束 ＋</button></div>
    <label>开始手柄<input type="range" aria-label={`开始手柄 ${clip.instance_id}`} min={full?0:Math.max(0,Math.min(start,clip.start_ms/1000)-10)} max={full?limit:Math.min(limit,Math.max(end,clip.end_ms/1000)+10)} step={0.001} value={start} disabled={busy} onChange={e=>change(Math.min(Number(e.target.value),end-0.001),end)} /></label>
    <label>结束手柄<input type="range" aria-label={`结束手柄 ${clip.instance_id}`} min={full?0:Math.max(0,Math.min(start,clip.start_ms/1000)-10)} max={full?limit:Math.min(limit,Math.max(end,clip.end_ms/1000)+10)} step={0.001} value={end} disabled={busy} onChange={e=>change(start,Math.max(start+0.001,Number(e.target.value)))} /></label>
    <button onClick={()=>setFull(!full)}>{full?"缩放到片段附近":"显示完整素材时间尺"}</button>
    {onAudition?<><button disabled={!valid} onClick={()=>onAudition("start")}>试听开头</button><button disabled={!valid} onClick={()=>onAudition("end")}>试听结尾</button><button disabled={!valid} onClick={()=>onAudition("whole")}>播放片段</button></>:<button disabled={!valid} onClick={()=>onJump(start)}>跳转 {start.toFixed(2)} 秒</button>}
    {!onRange&&<button disabled={busy||!valid} onClick={()=>void save({source_start_ms:Math.round(start*1000),source_end_ms:Math.round(end*1000)})}>保存范围</button>}
    <p className="helper-text">{onRange?"范围草稿即时试听，统一点击保存修改；变更范围会重新提取字幕并重置已校正字幕。":"保存范围会重新提取字幕，请之后再校正文字。"}</p>
    <label>显示字幕<textarea aria-label={`字幕 ${clip.instance_id}`} value={draft} disabled={busy} maxLength={2000} onChange={event=>{setDraft(event.target.value);setMessage("");}} /></label>
    <button disabled={busy||!draft.trim()} onClick={()=>void save({display_text:draft.trim()})}>保存字幕</button>
    <button disabled={busy} onClick={()=>void save({deleted:!clip.deleted})}>{clip.deleted ? "恢复片段" : "删除片段"}</button>
    {actions}{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  </li>;
}
