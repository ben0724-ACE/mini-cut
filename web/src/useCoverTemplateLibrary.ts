import {useCallback,useEffect,useRef,useState} from "react";
import {coverTemplateChanged,listCoverTemplates,writeCoverTemplate,renameCoverTemplate,deleteCoverTemplate,type CoverTemplate,type CoverTemplateSource} from "./coverApi";

export function useCoverTemplateLibrary(){
  const [templates,setTemplates]=useState<CoverTemplate[]>([]);
  const [loading,setLoading]=useState(true);const [loadError,setLoadError]=useState("");
  const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [retry,setRetry]=useState(0);
  const lock=useRef(false);const refresh=useCallback(()=>setRetry(value=>value+1),[]);
  useEffect(()=>{window.addEventListener(coverTemplateChanged,refresh);return()=>window.removeEventListener(coverTemplateChanged,refresh);},[refresh]);
  useEffect(()=>{const controller=new AbortController();setLoading(true);setLoadError("");listCoverTemplates(controller.signal).then(value=>{if(!controller.signal.aborted){setTemplates(value);setLoading(false);}}).catch(reason=>{if(!controller.signal.aborted){setLoadError(reason instanceof Error?reason.message:"无法读取封面模板库");setLoading(false);}});return()=>controller.abort();},[retry]);
  async function mutate<T>(operation:()=>Promise<T>,apply:(value:T)=>void):Promise<T|undefined>{if(lock.current)return;lock.current=true;setBusy(true);setError("");try{const value=await operation();apply(value);window.dispatchEvent(new Event(coverTemplateChanged));return value;}catch(reason){setError(reason instanceof Error?reason.message:"封面模板操作失败");}finally{lock.current=false;setBusy(false);}}
  function upsert(template:CoverTemplate){setTemplates(current=>[...current.filter(item=>item.template_id!==template.template_id),template].sort((a,b)=>a.name.localeCompare(b.name)));}
  return {templates,loading,loadError,busy,error,refresh,
    create:(name:string,source:CoverTemplateSource)=>mutate(()=>writeCoverTemplate(name,source),upsert),
    update:(id:string,name:string,source:CoverTemplateSource)=>mutate(()=>writeCoverTemplate(name,source,id),upsert),
    rename:(id:string,name:string)=>mutate(()=>renameCoverTemplate(id,name),upsert),
    remove:(id:string)=>mutate(async()=>{await deleteCoverTemplate(id);return true;},()=>setTemplates(current=>current.filter(item=>item.template_id!==id))),
  };
}
