import { useState, type ReactNode } from "react";
import type { HighlightClip, SplitRange } from "./api";

type Changes = {deleted?: boolean; display_text?: string; source_start_ms?: number; source_end_ms?: number};
export function OutputItemEditor({clip, busy, onSave, onJump, actions, range, onRange, onAudition, durationMs, onSplitPreview, onSplitApply, splitDisabled}: {clip: HighlightClip; busy: boolean; onSave: (changes: Changes) => Promise<void>; onJump: (seconds?:number) => void; actions?:ReactNode;range?:{start:number;end:number};onRange?:(start:number,end:number)=>void;onAudition?:(part:"start"|"end"|"whole")=>void;durationMs?:number;onSplitPreview?:(lines:string[])=>Promise<SplitRange[]>;onSplitApply?:(lines:string[])=>Promise<void>;splitDisabled?:boolean}) {
  const [splitPreview,setSplitPreview]=useState<{lines:string[];ranges:SplitRange[]}|null>(null);
  const [splitting,setSplitting]=useState(false);
  const [draft, setDraft] = useState(clip.text);
  const [localStart, setStart] = useState(clip.start_ms / 1000);
  const [localEnd, setEnd] = useState(clip.end_ms / 1000);
  const start=range?range.start/1000:localStart;const end=range?range.end/1000:localEnd;
  const [step,setStep]=useState(0.5);
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
    {onAudition?<><button disabled={!valid} onClick={()=>onAudition("start")}>试听开头</button><button disabled={!valid} onClick={()=>onAudition("end")}>试听结尾</button><button disabled={!valid} onClick={()=>onAudition("whole")}>播放片段</button></>:<button disabled={!valid} onClick={()=>onJump(start)}>跳转 {start.toFixed(2)} 秒</button>}
    {!onRange&&<button disabled={busy||!valid} onClick={()=>void save({source_start_ms:Math.round(start*1000),source_end_ms:Math.round(end*1000)})}>保存范围</button>}
    <p className="helper-text">{onRange?"范围草稿即时试听，统一点击保存修改；变更范围会重新提取字幕并重置已校正字幕。":"保存范围会重新提取字幕，请之后再校正文字。"}</p>
    <label>显示字幕<textarea aria-label={`字幕 ${clip.instance_id}`} value={draft} disabled={busy||splitting} maxLength={12000} onChange={event=>{setDraft(event.target.value);setMessage("");setSplitPreview(null);}} /></label>
    {onSplitPreview && onSplitApply && <div className="manual-split">
      <p className="helper-text">手动分句：在上方字幕中每句换一行（也可按对话轮次换行），仅添加换行或标点。先分句，再校正文字；时间来自原转录，建议试听确认。</p>
      {clip.transcript_text && <button disabled={busy||splitting||splitDisabled} onClick={()=>{setDraft(clip.transcript_text!);setSplitPreview(null);setError("");}}>使用转录原文</button>}
      <button disabled={busy||splitting||splitDisabled||clip.deleted||draft.split("\n").filter(s=>s.trim()).length<2} onClick={async()=>{setSplitting(true);setError("");setSplitPreview(null);const lines=draft.split("\n").map(s=>s.trim()).filter(Boolean);try{const ranges=await onSplitPreview(lines);setSplitPreview({lines,ranges});}catch(reason){setError(reason instanceof Error?reason.message:"无法匹配分句时间");}finally{setSplitting(false);}}}>{splitting?"正在处理…":"预览分句时间"}</button>
      {splitPreview && <><ol>{splitPreview.ranges.map((part,index)=><li key={index}><span className="muted">{(part.start_ms/1000).toFixed(2)}–{(part.end_ms/1000).toFixed(2)} 秒</span><p>{part.text}</p></li>)}</ol><p className="helper-text">保留全部音视频和停顿，确认后保存为新版本；不渲染视频。</p><button disabled={busy||splitting||splitDisabled} onClick={async()=>{setSplitting(true);setError("");try{await onSplitApply(splitPreview.lines);setSplitPreview(null);}catch(reason){setError(reason instanceof Error?reason.message:"分句保存失败");}finally{setSplitting(false);}}}>确认分句</button><button disabled={splitting} onClick={()=>setSplitPreview(null)}>取消分句</button></>}
    </div>}
    <button disabled={busy||splitting||!draft.trim()} onClick={()=>void save({display_text:draft.trim()})}>保存字幕</button>
    <button disabled={busy} onClick={()=>void save({deleted:!clip.deleted})}>{clip.deleted ? "恢复片段" : "删除片段"}</button>
    {actions}{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  </li>;
}
