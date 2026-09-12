import { useState } from "react";
import type { HighlightClip } from "./api";

export function OutputItemEditor({clip, busy, onSave, onJump}: {clip: HighlightClip; busy: boolean; onSave: (changes: {deleted?: boolean; display_text?: string}) => Promise<void>; onJump: () => void}) {
  const [draft, setDraft] = useState(clip.text); const [error, setError] = useState(""); const [message, setMessage] = useState("");
  async function save(changes: {deleted?: boolean; display_text?: string}) {
    setError(""); setMessage("");
    try {await onSave(changes); setMessage(changes.display_text !== undefined ? "字幕已保存" : "片段状态已保存（未保存字幕草稿）");}
    catch (reason: unknown) {setError(reason instanceof Error ? reason.message : "保存失败");}
  }
  return <li className={clip.deleted ? "segment segment--delete" : "segment"}><button onClick={onJump}>跳转 {(clip.start_ms / 1000).toFixed(2)} 秒</button><p>{clip.role === "hook" ? "原话钩子" : "正文"} · {clip.deleted ? "已删除" : "保留"}</p><label>显示字幕<textarea aria-label={`字幕 ${clip.instance_id}`} value={draft} disabled={busy} maxLength={2000} onChange={event => {setDraft(event.target.value); setMessage("");}} /></label><p>原文：{clip.source_text ?? clip.text}</p><button disabled={busy || !draft.trim()} onClick={() => void save({display_text:draft.trim()})}>保存字幕</button><button disabled={busy} onClick={() => void save({deleted:!clip.deleted})}>{clip.deleted ? "恢复片段" : "删除片段"}</button>{error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}</li>;
}
