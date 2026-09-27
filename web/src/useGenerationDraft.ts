import { useCallback, useEffect, useState } from "react";
import { getGenerationDraft, saveGenerationDraft, type GenerationHistoryEntry } from "./api";
import { defaultGenerationDraft, draftFromHistory, normalizeGenerationDraft, type GenerationDraft } from "./generationDraft";

interface SaveSession {
  pending: GenerationDraft | null;
  running: Promise<void> | null;
  error: string;
  listeners: Set<() => void>;
}
const sessions = new Map<string, SaveSession>();
const keyFor = (project:string, asset:string) => `minicut:generation-draft:${encodeURIComponent(project)}:${encodeURIComponent(asset)}`;
function sessionFor(key:string): SaveSession {
  let session = sessions.get(key);
  if (!session) {session = {pending:null, running:null, error:"", listeners:new Set()}; sessions.set(key, session);}
  return session;
}
function notify(session:SaveSession) {session.listeners.forEach(listener=>listener());}
function remember(key:string, draft:GenerationDraft) {
  // Keep unsynced keystrokes through page reloads, including failed API writes.
  try {localStorage.setItem(key, JSON.stringify(draft));} catch { /* API persistence still works if browser storage is unavailable. */ }
}
function pendingDraft(key:string): GenerationDraft | null {
  try {
    const raw = JSON.parse(localStorage.getItem(key) ?? "null") as Partial<GenerationDraft> | null;
    const value = raw ? {...raw, limit_duration:raw.limit_duration ?? true, custom_preset_id:raw.custom_preset_id??null, custom_preset_name:raw.custom_preset_name??null,custom_prompt:raw.custom_prompt??null} as GenerationDraft : null;
    if (!value || !value.prompts || typeof value.instructions !== "string" || !(value.preset in defaultGenerationDraft().prompts)) return null;
    const defaults = defaultGenerationDraft();
    const metadata = ["custom_preset_id", "custom_preset_name", "custom_prompt"];
    if (Object.keys(defaults).filter(key=>!metadata.includes(key)).some(key=>typeof value[key as keyof GenerationDraft] !== typeof defaults[key as keyof GenerationDraft])) return null;
    if (metadata.some(key=>value[key as keyof GenerationDraft] !== null && typeof value[key as keyof GenerationDraft] !== "string")) return null;
    return value;
  } catch {return null;}
}
function flush(project:string, asset:string): Promise<void> {
  const key = keyFor(project, asset);
  const session = sessionFor(key);
  if (session.running) return session.running;
  session.error = "";
  session.running = (async()=>{
    while (session.pending) {
      const draft = session.pending;
      session.pending = null;
      try {
        await saveGenerationDraft(project, asset, draft);
        try {
          if (localStorage.getItem(key) === JSON.stringify(draft)) localStorage.removeItem(key);
        } catch { /* Saving to the project has succeeded. */ }
      } catch (reason) {
        session.pending ??= draft;
        session.error = reason instanceof Error ? reason.message : "草稿保存失败";
        throw reason;
      }
    }
  })().finally(()=>{session.running = null; notify(session);});
  notify(session);
  void session.running.catch(()=>{});
  return session.running;
}
function queue(project:string, asset:string, draft:GenerationDraft) {
  const session = sessionFor(keyFor(project, asset));
  remember(keyFor(project, asset), draft);
  session.pending = draft;
  void flush(project, asset).catch(()=>{});
}

export function useGenerationDraft(project:string, asset:string) {
  const [draft, setDraft] = useState(defaultGenerationDraft);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState(0);
  const [, refresh] = useState(0);
  const key = keyFor(project, asset);
  const session = sessionFor(key);
  useEffect(()=>{
    const listener = ()=>refresh(value=>value+1);
    session.listeners.add(listener);
    return ()=>{session.listeners.delete(listener);};
  }, [session]);
  useEffect(()=>{
    const controller = new AbortController();
    setLoaded(false); setLoadError("");
    const load = async()=>{
      // A previous mount may still be saving. Read after it finishes so an
      // older GET response cannot replace the just-saved draft on remount.
      if (session.running) await session.running.catch(()=>{});
      return getGenerationDraft(project, asset, controller.signal);
    };
    load().then(response=>{
      if (controller.signal.aborted) return;
      const pending = session.pending ?? pendingDraft(key);
      const defaults = defaultGenerationDraft();
      const restored = pending ?? (response.draft ? {...defaults,...response.draft,prompts:{...defaults.prompts,...response.draft.prompts}} : response.history ? draftFromHistory(response.history) : defaults);
      const next = normalizeGenerationDraft(restored);
      setDraft(next); setLoaded(true);
      const messages = {
        asset:"已恢复当前素材的草稿", project:"已沿用项目最近保存的配置，各素材草稿分别保存",
        history:"已从当前素材最近一次生成恢复配置", project_history:"已沿用项目最近一次生成的配置",
        default:"当前使用默认配置，修改后自动保存到项目",
      };
      setNotice(pending ? "已恢复尚未同步的本机草稿，正在保存到项目" : messages[response.source]);
      if (!pending && response.history?.missing_fields.length) setNotice(`${messages[response.source]}；旧记录缺失的字段已用当前默认设置补齐，请核对。这些默认值不代表当时的配置。`);
      if (pending || response.source !== "asset" || next !== restored) queue(project, asset, next);
    }).catch(reason=>{if (!controller.signal.aborted) setLoadError(reason instanceof Error ? reason.message : "无法恢复生成草稿");});
    return ()=>controller.abort();
  }, [project, asset, key, retry, session]);
  const change = useCallback((next:GenerationDraft)=>{
    setDraft(next); queue(project, asset, next);
  }, [project, asset]);
  const loadHistory = (entry:GenerationHistoryEntry)=>{
    change(draftFromHistory(entry));
    setNotice(entry.missing_fields.length ? "已载入历史为新草稿；未记录的字段已用当前默认设置补齐，请核对。这些默认值不代表当时的配置。" : "已载入历史为新草稿；尚未生成，现有作品保持不变");
  };
  return {draft, loaded, loadError, notice, change, loadHistory,
    saving:!!session.running || !!session.pending,
    saveError:session.error,
    flush:()=>flush(project, asset),
    retryLoad:()=>setRetry(value=>value+1),
  };
}
