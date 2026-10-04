import {useEffect, useRef, useState} from "react";
import {renameOutput, type HighlightOutput, type HighlightResult, type HighlightClip} from "./api";
import {QuickPreview} from "./QuickPreview";

const pageSize = 20;
export function CleanupReview({project,collection,plan,sourceUrl,sourceDuration,disabled,onUpdated,onRestore}:{project:string;collection:string;plan:HighlightOutput;sourceUrl:string;sourceDuration:number;disabled:boolean;onUpdated:(result:HighlightResult)=>void;onRestore:(id:string)=>Promise<void>}) {
  const [name,setName]=useState(plan.title);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [page,setPage]=useState(0);
  const [audition,setAudition]=useState<{clip:HighlightClip;cleaned:boolean;sequence:number}|null>(null);
  const player=useRef<HTMLDivElement>(null);
  const removed=plan.clips.filter(c=>c.cleanup_category&&c.deleted);
  const currentPage=Math.min(page,Math.max(0,Math.ceil(removed.length/pageSize)-1));
  useEffect(()=>{if(audition)player.current?.scrollIntoView?.({block:"nearest"});},[audition]);
  async function run(operation:()=>Promise<void>){setBusy(true);setError("");try{await operation();}catch(reason){setError(reason instanceof Error?reason.message:"保存失败");}finally{setBusy(false);}}
  function listen(clip:HighlightClip,cleaned:boolean){setAudition(previous=>({clip,cleaned,sequence:(previous?.sequence??0)+1}));}
  const before=audition?Math.max(0,audition.clip.start_ms-1500):0;
  const after=audition?Math.min(sourceDuration,audition.clip.end_ms+1500):0;
  const clips=audition?(audition.cleaned?plan.clips.filter(c=>!c.deleted&&c.end_ms>before&&c.start_ms<after).map(c=>({...c,start_ms:Math.max(before,c.start_ms),end_ms:Math.min(after,c.end_ms)})):[{...audition.clip,deleted:false,start_ms:before,end_ms:after}]):[];
  return <section aria-label="口播清理审阅"><h3>口播清理</h3><p>此流程不生成文案。封面文字可在封面设计中手动填写。</p><label>作品名<input aria-label="作品名" value={name} maxLength={200} disabled={disabled||busy} onChange={e=>setName(e.target.value)}/></label><button disabled={disabled||busy||!name.trim()||name.trim()===plan.title} onClick={()=>void run(async()=>onUpdated(await renameOutput(project,collection,plan.output_id,plan.revision,name.trim())))}>保存作品名</button><p>{(sourceDuration/1000).toFixed(1)} 秒 → {(plan.duration_ms/1000).toFixed(1)} 秒 · 当前自动删除 {removed.length} 处</p>
    <details><summary>查看删除清单与切点试听</summary>
      {audition&&<div ref={player} aria-label="切点试听播放器"><p>{audition.cleaned?"清理后切点":"原片上下文"} · 源 {(audition.clip.start_ms/1000).toFixed(2)}–{(audition.clip.end_ms/1000).toFixed(2)} 秒</p><QuickPreview sourceUrl={sourceUrl} title="清理切点试听" clips={clips} playSequence={audition.sequence} onDuration={()=>{}}/></div>}
      {removed.length===0&&<p>没有待恢复的自动删除。</p>}
      <ul>{removed.slice(currentPage*pageSize,(currentPage+1)*pageSize).map(c=><li key={c.instance_id}><p>{c.cleanup_category} · {(c.start_ms/1000).toFixed(2)}–{(c.end_ms/1000).toFixed(2)} 秒 · {c.text}</p><button onClick={()=>listen(c,false)}>试听原片上下文</button><button onClick={()=>listen(c,true)}>试听清理后切点</button><button disabled={disabled||busy} onClick={()=>void run(()=>onRestore(c.instance_id))}>恢复此处</button></li>)}</ul>
      {removed.length>pageSize&&<nav aria-label="删除清单分页"><button disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>上一页</button><span>第 {currentPage+1} / {Math.ceil(removed.length/pageSize)} 页 · 共 {removed.length} 处</span><button disabled={(currentPage+1)*pageSize>=removed.length} onClick={()=>setPage(currentPage+1)}>下一页</button></nav>}
    </details>{error&&<p role="alert">{error}</p>}</section>;
}
