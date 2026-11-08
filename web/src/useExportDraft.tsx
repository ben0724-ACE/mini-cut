import {useCallback,useEffect,useState} from "react";
import {defaultExportDraft,getExportDraft,saveExportDraft,type ExportDraft} from "./exportSettingsApi";

interface Session {pending:ExportDraft|null;running:Promise<void>|null;error:string;listeners:Set<()=>void>;current:ExportDraft|null;version:number}
const sessions=new Map<string,Session>();
const storageKey=(route:string)=>`minicut:export-draft:${route}`;
function sessionFor(route:string){let session=sessions.get(route);if(!session){session={pending:null,running:null,error:"",listeners:new Set(),current:null,version:0};sessions.set(route,session);}return session;}
function notify(session:Session){session.listeners.forEach(listener=>listener());}
function remembered(route:string):ExportDraft|null{
  try {const draft=JSON.parse(localStorage.getItem(storageKey(route))??"null");return draft?.options&&draft?.overrides&&typeof draft.options.subtitle_mode==="string"?draft:null;}catch{return null;}
}
function flush(route:string):Promise<void>{
  const session=sessionFor(route);if(session.running)return session.running;session.error="";
  session.running=(async()=>{
    while(session.pending){const draft=session.pending;session.pending=null;
      try {await saveExportDraft(route,draft);try{if(localStorage.getItem(storageKey(route))===JSON.stringify(draft))localStorage.removeItem(storageKey(route));}catch{/* Backend save succeeded. */}}
      catch(reason){session.pending??=draft;session.error=reason instanceof Error?reason.message:"导出设置保存失败";throw reason;}
    }
  })().finally(()=>{session.running=null;notify(session);});notify(session);void session.running.catch(()=>{});return session.running;
}
function queue(route:string,draft:ExportDraft){const session=sessionFor(route);session.pending=draft;session.current=draft;session.version++;notify(session);try{localStorage.setItem(storageKey(route),JSON.stringify(draft));}catch{/* Keep the in-memory draft and save to the backend. */}void flush(route).catch(()=>{});}

export function useExportDraft(route:string){
  const [draft,setDraft]=useState(defaultExportDraft);const [loadedRoute,setLoadedRoute]=useState("");const loaded=loadedRoute===route;const [loadError,setLoadError]=useState("");const [notice,setNotice]=useState("");const [retry,setRetry]=useState(0);const [,refresh]=useState(0);const session=sessionFor(route);
  useEffect(()=>{const listener=()=>{if(session.current)setDraft(session.current);refresh(value=>value+1);};session.listeners.add(listener);return()=>{session.listeners.delete(listener);};},[session]);
  useEffect(()=>{
    const controller=new AbortController();setLoadedRoute("");setLoadError("");
    async function load(){if(session.running)await session.running.catch(()=>{});const version=session.version;return {response:await getExportDraft(route,controller.signal),version};}
    load().then(({response,version})=>{
      if(controller.signal.aborted)return;
      const pending=session.pending??remembered(route);const restored=pending??(session.version!==version?session.current:null)??response.draft;
      session.current=restored;session.version++;notify(session);
      setDraft(restored);setLoadedRoute(route);setNotice(pending?"已恢复未同步设置，正在保存":response.source==="saved"?"已恢复当前导出设置":response.source==="project"?"已沿用本项目最近的同模式设置，请核对裁剪区域":"当前使用默认设置，修改后自动保存");
      if(pending||response.source==="project")queue(route,restored);
    }).catch(reason=>{if(controller.signal.aborted)return;const pending=session.pending??remembered(route);if(pending){setDraft(pending);setLoadedRoute(route);setNotice("已恢复本机未同步设置，正在重试保存");queue(route,pending);}else setLoadError(reason instanceof Error?reason.message:"无法读取导出设置");});
    return()=>controller.abort();
  },[route,retry,session]);
  const change=useCallback((next:ExportDraft)=>{setDraft(next);queue(route,next);},[route]);
  return {draft,change,loaded,loadError,notice,saveError:session.error,saving:!!session.pending||!!session.running,flush:()=>flush(route),retryLoad:()=>setRetry(value=>value+1)};
}

export function ExportDraftStatus({state}:{state:ReturnType<typeof useExportDraft>}){
  const reviewNotice=state.loaded&&state.notice.includes("请核对裁剪区域");
  if(state.loaded&&!state.loadError&&!state.saveError&&!state.saving&&!reviewNotice)return null;
  return <div className="helper-text">
    {state.loadError?<p role="alert">{state.loadError}<button type="button" onClick={state.retryLoad}>重试读取导出设置</button></p>:!state.loaded?<p role="status">正在读取导出设置…</p>:state.saving&&!state.saveError?<p role="status">正在保存导出设置…</p>:null}
    {reviewNotice&&<p>{state.notice}</p>}
    {state.saveError&&<p role="alert">导出设置保存失败，修改保留在本机：{state.saveError}<button type="button" onClick={()=>void state.flush().catch(()=>{})}>重试保存导出设置</button></p>}
  </div>;
}
