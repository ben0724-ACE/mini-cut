import {useEffect,useRef,useState} from "react";
import type {HighlightOutput,HighlightResult} from "./api";
import {exportSettingsRoute,getExportDraft,type ExportOptions} from "./exportSettingsApi";
import {outputSettingsLabel} from "./OutputSettingsSummary";
import {QuickPreview} from "./QuickPreview";
import {RenderedPreview} from "./RenderedPreview";

export function MinimalPreview({project,result,output,disabled=false}:{project:string;result:HighlightResult;output:HighlightOutput;disabled?:boolean}){
  const [snapshot,setSnapshot]=useState<{revision:number;options:ExportOptions;id:string}|null>(null);
  const [rendered,setRendered]=useState(false);const [loading,setLoading]=useState(false);const [error,setError]=useState("");
  const request=useRef<AbortController|null>(null);
  useEffect(()=>()=>request.current?.abort(),[project,result.collection_id,output.output_id,output.revision]);
  const sourceUrl=`/api/projects/${encodeURIComponent(project)}/media/source/${encodeURIComponent(result.asset_id)}`;
  const stale=!!snapshot&&snapshot.revision!==output.revision;
  async function generate(){
    if(disabled||request.current)return;const controller=new AbortController();request.current=controller;setLoading(true);setError("");
    try{
      const {draft}=await getExportDraft(exportSettingsRoute(project,result.collection_id,output.output_id),controller.signal);
      if(!controller.signal.aborted){setSnapshot({revision:output.revision,options:draft.options,id:crypto.randomUUID()});setRendered(true);}
    }catch(reason){if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"无法读取成片设置");}
    finally{if(request.current===controller){request.current=null;setLoading(false);}}
  }
  return <section className="minimal-preview" aria-label="作品试听">
    <h3 title={output.title}>{output.title}</h3>
    <div className="preview-mode-switch minimal-preview-controls" role="group" aria-label="预览方式">
      <button type="button" aria-pressed={!rendered} disabled={loading} onClick={()=>setRendered(false)}>快速预览</button>
      <button type="button" aria-pressed={rendered} disabled={disabled||loading} onClick={()=>snapshot?setRendered(true):void generate()}>{loading?"正在读取设置…":"成片预览"}</button>
      {snapshot&&<button type="button" disabled={disabled||loading} onClick={()=>void generate()}>更新成片预览</button>}
    </div>
    <div className="minimal-media">{rendered&&snapshot?<RenderedPreview key={snapshot.id} project={project} collection={result.collection_id} output={output.output_id} revision={snapshot.revision} options={snapshot.options} sourceUrl={sourceUrl} title={output.title}/>:<QuickPreview compact sourceUrl={sourceUrl} title={output.title} clips={output.clips} onDuration={()=>{}}/>}</div>
    {error&&<p role="alert" className="minimal-preview-hint">{error}</p>}
    {rendered&&snapshot?<><p className="helper-text minimal-preview-hint">{outputSettingsLabel(snapshot.options)}</p>{stale&&<p role="status" className="preview-stale">作品版本已变化，请更新成片预览。</p>}</>:<p className="helper-text minimal-preview-hint">源视频试听 · 点击成片预览查看字幕、画幅与转场</p>}
    {output.workflow==="speech_cleanup"?<p className="helper-text minimal-preview-hint">此流程不生成文案</p>:<details className="minimal-reason"><summary>选材理由</summary><p className="helper-text">{output.reason}</p></details>}
  </section>;
}
