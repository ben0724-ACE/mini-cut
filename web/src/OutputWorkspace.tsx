import { createPortal } from "react-dom";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { saveOutputSubtitleSettings, previewManualSplit, applyManualSplit, splitOutputSentences, saveOutputRanges, getHighlights, editOutputItem, reorderOutput, getOutputVersions, type HighlightResult, type HighlightClip } from "./api";
import { QuickPreview, type Audition } from "./QuickPreview";
import { registerDraftGuard } from "./draftNavigation";
import { RenderedPreview } from "./RenderedPreview";
import { OutputItemEditor } from "./OutputItemEditor";
import { OutputSubtitleSettings } from "./OutputSubtitleSettings";
import { OutputOrderControls } from "./OutputOrderControls";
import { CoverEditor } from "./CoverEditor";
import { OutputExport } from "./OutputExport";
import { Workbench, type WorkbenchTab } from "./Workbench";
import { outputBoundaryWarnings } from "./GenerationDetails";
import {exportSettingsRoute,type ExportDraft,type ExportOptions} from "./exportSettingsApi";
import {useExportDraft} from "./useExportDraft";
import {effectiveOutputOptions,outputSettingsLabel} from "./OutputSettingsSummary";
import {OutputSettingsControls} from "./OutputSettingsControls";
import {ExportPresetControls} from "./ExportPresetControls";
import {subtitleSettingsFromPlan} from "./SubtitleAppearanceControls";
import {ExportDraftStatus} from "./useExportDraft";
interface Panels {preview:ReactNode;edit:ReactNode;exportPanel:ReactNode}
type EditSection = "frame" | "subtitles" | "sentences" | "hook";
const editSections:{id:EditSection;label:string}[]=[{id:"frame",label:"画面设置"},{id:"subtitles",label:"字幕设置"},{id:"sentences",label:"逐句编辑"},{id:"hook",label:"开场预告"}];
export function OutputWorkspace({project,collection,output,compose,onUpdated,onDirty,onExportSubmitted,onEditRequested,onBatchSettingsRequested,batchPreviewRequest}:{project:string;collection:string;output:string;compose?:(panels:Panels)=>ReactNode;onUpdated?:(result:HighlightResult)=>void;onDirty?:(dirty:boolean)=>void;onExportSubmitted?:(entries:{outputId:string;taskId:string}[])=>void;onEditRequested?:()=>void;onBatchSettingsRequested?:()=>void;batchPreviewRequest?:{output:string;id:string}}) {
  const singleSettings=useExportDraft(exportSettingsRoute(project,collection,output));
  const batchSettings=useExportDraft(exportSettingsRoute(project,collection));
  const [previewSource,setPreviewSource]=useState<"output"|"batch">("output");
  const outputSettings=previewSource==="batch"&&batchSettings.draft.settings_source==="uniform"?batchSettings:singleSettings;
  const effectiveOptions=effectiveOutputOptions(outputSettings.draft,outputSettings===batchSettings?output:undefined);
  const [localPanel,setLocalPanel]=useState<WorkbenchTab>(new URLSearchParams(window.location.search).get("panel")==="export"?"export":"edit");
  const [previewSnapshot,setPreviewSnapshot]=useState<{revision:number;options:ExportOptions;id:string;source:"output"|"batch"}|null>(null);
  const [subtitleDirty,setSubtitleDirty]=useState(false);
  const editTabsId=useId();
  const [editSection,setEditSection]=useState<EditSection>("frame");
  const [hookSourceId,setHookSourceId]=useState("");
  const [textDrafts,setTextDrafts]=useState<Record<string,boolean>>({});
  const onTextDraftChange=useCallback((id:string,hasDraft:boolean)=>setTextDrafts(previous=>{
    if(Boolean(previous[id])===hasDraft)return previous;
    const next={...previous};
    if(hasDraft)next[id]=true;else delete next[id];
    return next;
  }),[]);
  const [result,setResult]=useState<HighlightResult|null>(null);const [error,setError]=useState("");const [saving,setBusy]=useState(false);const [coverDirty,setCoverDirty]=useState(false);const [coverVersion,setCoverVersion]=useState<number>();const busy=saving||coverDirty;const lock=useRef(false);
  const [ranges,setRanges]=useState<Record<string,{start:number;end:number}>>({});
  const [undo,setUndo]=useState<typeof ranges[]>([]);const [redo,setRedo]=useState<typeof ranges[]>([]);
  const [audition,setAudition]=useState<Audition>();const [rendered,setRendered]=useState(false);const [duration,setDuration]=useState(0);
  const [navigation,setNavigation]=useState<(()=>void)|null>(null);
  const dirty=Object.keys(ranges).length>0;
  useEffect(()=>{onDirty?.(dirty||coverDirty||subtitleDirty||Object.values(textDrafts).some(Boolean));return()=>onDirty?.(false);},[dirty,coverDirty,subtitleDirty,textDrafts,onDirty]);
  useEffect(()=>{if(!dirty)return;const unload=(event:BeforeUnloadEvent)=>event.preventDefault();window.addEventListener("beforeunload",unload);const unregister=registerDraftGuard(proceed=>setNavigation(()=>proceed));return()=>{window.removeEventListener("beforeunload",unload);unregister();};},[dirty]);
  function changeRange(id:string,start:number,end:number){setUndo([...undo,ranges]);setRedo([]);setRanges({...ranges,[id]:{start,end}});setRendered(false);}
  function discard(){setRanges({});setUndo([]);setRedo([]);}
  const [jumpTo,setJumpTo]=useState<{ms:number;sequence:number}>();
  const [versions,setVersions]=useState<Awaited<ReturnType<typeof getOutputVersions>>>([]);
  const [actionError,setActionError]=useState("");const [historyError,setHistoryError]=useState("");const [viewVersion,setViewVersion]=useState<number|undefined>();
  async function update(operation:()=>Promise<HighlightResult>){if(lock.current)throw new Error("请等待当前保存完成");lock.current=true;setBusy(true);setActionError("");try{const updated=await operation();setJumpTo(undefined);setResult(updated);onUpdated?.(updated);setViewVersion(undefined);setVersions([]);}finally{lock.current=false;setBusy(false);}}
  useEffect(()=>{const controller=new AbortController();getHighlights(project,collection,controller.signal).then(value=>{if(!controller.signal.aborted)setResult(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"读取作品失败");});return()=>controller.abort();},[project,collection]);
  const lastBatchRequest=useRef("");
  useEffect(()=>{
    const saved=result?.outputs.find(plan=>plan.output_id===output);
    if(!batchPreviewRequest||batchPreviewRequest.output!==output||lastBatchRequest.current===batchPreviewRequest.id||!saved||!singleSettings.loaded||!batchSettings.loaded||singleSettings.loadError||batchSettings.loadError)return;
    const options=batchSettings.draft.settings_source==="uniform"?effectiveOutputOptions(batchSettings.draft,output):singleSettings.draft.options;
    lastBatchRequest.current=batchPreviewRequest.id;
    setViewVersion(undefined);setPreviewSource("batch");setPreviewSnapshot({revision:saved.revision,options:{...options},id:batchPreviewRequest.id,source:"batch"});setRendered(true);
  },[batchPreviewRequest,result,output,singleSettings.loaded,singleSettings.loadError,singleSettings.draft,batchSettings.loaded,batchSettings.loadError,batchSettings.draft]);
  function openEdit(section:EditSection){setEditSection(section);setLocalPanel("edit");onEditRequested?.();}
  if(error)return <p role="alert">{error}</p>;if(!result)return <p role="status">正在读取作品…</p>;
  const plan=result.outputs.find(plan=>plan.output_id===output);if(!plan)return <p role="alert">作品不存在</p>;
  const currentPlan=plan;
  const historical=viewVersion!==undefined&&viewVersion!==plan.revision;
  const visibleVersion=versions.find(version=>version.revision===viewVersion);
  const visibleClips=visibleVersion?.clips??plan.clips;
  const sentenceDraft=visibleClips.some(clip=>clip.role==="body"&&textDrafts[clip.instance_id]);
  const hookDraft=visibleClips.some(clip=>clip.role==="hook"&&textDrafts[clip.instance_id]);
  const subtitlePlan=visibleVersion?{...plan,...visibleVersion}:plan;
  const draftClips=visibleClips.map(c=>ranges[c.instance_id]?{...c,start_ms:ranges[c.instance_id].start,end_ms:ranges[c.instance_id].end}:c);
  const limit=duration||result.source_duration_ms||0;
  const valid=draftClips.every(c=>Number.isFinite(c.start_ms)&&Number.isFinite(c.end_ms)&&c.start_ms>=0&&c.end_ms>c.start_ms&&(!limit||c.end_ms<=limit));
  async function saveDraft(){if(!plan||!valid)return false;try{await update(()=>saveOutputRanges(project,collection,output,plan.revision,Object.entries(ranges).map(([instance_id,r])=>({instance_id,source_start_ms:r.start,source_end_ms:r.end}))));discard();setRendered(false);return true;}catch(reason){setActionError(String(reason));return false;}}
  const sourceUrl=`/api/projects/${encodeURIComponent(project)}/media/source/${encodeURIComponent(result.asset_id)}`;
  const sourceTime=(visibleClips.find(clip=>!clip.deleted)?.start_ms??0)/1000;
  const unsavedSubtitles=subtitleDirty||Object.values(textDrafts).some(Boolean);
  const previewStale=!!previewSnapshot&&(previewSnapshot.revision!==(viewVersion??plan.revision)||JSON.stringify(previewSnapshot.options)!==JSON.stringify(effectiveOptions));
  const preview=<>
    <div className="output-settings-toolbar" role="region" aria-label="输出设置">
      <span>{outputSettings.loaded?outputSettingsLabel(effectiveOptions):"正在读取作品设置…"}</span><button type="button" disabled={previewSource==="batch"&&!onBatchSettingsRequested} onClick={()=>previewSource==="batch"?onBatchSettingsRequested?.():openEdit("frame")}>{previewSource==="batch"?"调整批量配置":"调整设置"}</button>
    </div>
    {previewSource==="batch"&&<p className="batch-preview-label">批量效果预览 · {batchSettings.draft.settings_source==="uniform"?"统一批量配置":"沿用作品设置"}<button type="button" onClick={()=>{setPreviewSource("output");setRendered(false);setPreviewSnapshot(null);}}>返回作品预览</button></p>}
    <h1 className="preview-title">{plan.title}</h1><p className="muted">v{viewVersion??plan.revision} · {((visibleVersion?.duration_ms??plan.duration_ms)/1000).toFixed(1)} 秒 · {previewSource==="batch"?"批量效果":"作品效果"}</p>
    <div className="preview-mode-switch" role="group" aria-label="预览方式"><button type="button" aria-pressed={!rendered} onClick={()=>setRendered(false)}>快速预览</button><button type="button" aria-pressed={rendered} disabled={!previewSnapshot||dirty} onClick={()=>setRendered(true)}>成片预览</button></div>
    {rendered&&!dirty&&previewSnapshot?<>
      <RenderedPreview key={previewSnapshot.id} project={project} collection={collection} output={output} revision={previewSnapshot.revision} options={previewSnapshot.options} title={plan.title} jumpTo={jumpTo} sourceUrl={sourceUrl}/>
      {previewStale&&<p role="status" className="preview-stale">设置或作品版本已变化，请更新预览。当前画面保留上次生成的效果。</p>}
    </>:<QuickPreview sourceUrl={sourceUrl} title={plan.title} clips={draftClips.filter(c=>c.end_ms>c.start_ms&&c.start_ms>=0)} audition={audition} onDuration={setDuration}/>}
    <button className="primary-button" disabled={dirty||busy||unsavedSubtitles||!outputSettings.loaded||!!outputSettings.loadError||(previewSource==="batch"&&(!batchSettings.loaded||!!batchSettings.loadError))} onClick={()=>{setPreviewSnapshot({revision:viewVersion??plan.revision,options:{...effectiveOptions},id:crypto.randomUUID(),source:previewSource});setRendered(true);}}>{previewSnapshot?"更新成片预览":"生成成片预览"}</button>
    {outputSettings.loadError&&<p role="alert">{outputSettings.loadError}<button onClick={outputSettings.retryLoad}>重试读取作品设置</button></p>}
    {unsavedSubtitles&&<p>先保存字幕修改，再生成预览。</p>}
    {dirty&&<p>有未保存的范围修改；已有成片属于保存前的旧版本。</p>}
  </>;
  const boundaryWarnings=outputBoundaryWarnings(result.notes??[],plan.title);
  const subtitleSettings=<OutputSubtitleSettings key={`${collection}:${output}:${viewVersion??plan.revision}`} project={project} collection={collection} plan={subtitlePlan} disabled={busy||historical||dirty} disabledReason={historical?"历史版本只读，请切回当前版本后修改或翻译。":dirty?"请先保存或放弃范围修改，再修改或翻译字幕。":undefined} onDirty={setSubtitleDirty} onUpdated={updated=>{setResult(updated);onUpdated?.(updated);setViewVersion(undefined);setVersions([]);}} />;
  const hookCandidates=visibleClips.filter(clip=>clip.role==="body"&&!clip.deleted&&!visibleClips.some(hook=>hook.role==="hook"&&hook.segment_id===clip.segment_id&&hook.start_ms===clip.start_ms&&hook.end_ms===clip.end_ms));
  const selectedHookSource=hookCandidates.find(clip=>clip.instance_id===hookSourceId)??hookCandidates[0];
  function changeRole(clip:HighlightClip,role:"hook"|"body"){
    const rank=(entry:HighlightClip)=>(entry.instance_id===clip.instance_id?role:entry.role)==="hook"?0:1;
    const ordered=[...visibleClips].sort((left,right)=>rank(left)-rank(right));
    void update(()=>reorderOutput(project,collection,output,ordered.map(entry=>entry.instance_id),{[clip.instance_id]:role})).catch(reason=>setActionError(String(reason)));
  }
  function renderClip(clip:HighlightClip,index:number){
    return <OutputItemEditor
      key={(viewVersion??currentPlan.revision)+":"+clip.instance_id}
      clip={clip}
      subtitleMode={(visibleVersion??currentPlan).subtitle_mode??undefined}
      busy={busy||historical}
      splitDisabled={dirty||historical}
      onTextDraftChange={onTextDraftChange}
      onSplitPreview={async lines=>{if(dirty||historical)throw new Error("请先保存范围草稿并切回当前版本");return (await previewManualSplit(project,collection,output,clip.instance_id,currentPlan.revision,lines)).ranges;}}
      onSplitApply={lines=>update(()=>applyManualSplit(project,collection,output,clip.instance_id,currentPlan.revision,lines))}
      range={ranges[clip.instance_id]??{start:clip.start_ms,end:clip.end_ms}}
      durationMs={limit||undefined}
      onRange={(start,end)=>changeRange(clip.instance_id,start,end)}
      onAudition={part=>{setRendered(false);setAudition(previous=>({id:clip.instance_id,part,sequence:(previous?.sequence??0)+1}));}}
      onSave={changes=>dirty?Promise.reject(new Error("请先保存或放弃范围修改")):update(()=>editOutputItem(project,collection,output,clip.instance_id,changes))}
      onJump={seconds=>setJumpTo(previous=>({ms:seconds===undefined?clip.start_ms:Math.round(seconds*1000),sequence:(previous?.sequence??0)+1}))}
      actions={<>
        <button disabled={busy||historical||dirty||index===0||visibleClips[index-1]?.role!==clip.role} onClick={()=>{const order=visibleClips.map(entry=>entry.instance_id);[order[index-1],order[index]]=[order[index],order[index-1]];void update(()=>reorderOutput(project,collection,output,order,{})).catch(reason=>setActionError(String(reason)));}}>上移</button>
        <button disabled={busy||historical||dirty||index===visibleClips.length-1||visibleClips[index+1]?.role!==clip.role} onClick={()=>{const order=visibleClips.map(entry=>entry.instance_id);[order[index+1],order[index]]=[order[index],order[index+1]];void update(()=>reorderOutput(project,collection,output,order,{})).catch(reason=>setActionError(String(reason)));}}>下移</button>
        {clip.role==="hook"&&<button disabled={busy||historical||dirty||!!clip.deleted} onClick={()=>changeRole(clip,"body")}>取消开场预告</button>}
      </>}
    />;
  }
  async function applyPreset(next:ExportDraft){
    await singleSettings.flush();
    const subtitles=next.options.subtitle_settings;
    if(subtitles&&JSON.stringify(subtitles)!==JSON.stringify(subtitleSettingsFromPlan(currentPlan))){
      await update(()=>saveOutputSubtitleSettings(project,collection,output,currentPlan.revision,subtitles));
    }
    singleSettings.change({...next,options:{...next.options,subtitle_settings:null}});
    try{await singleSettings.flush();}catch{throw new Error("字幕设置已应用；画面和音频设置尚未同步，请点击重试保存导出设置。");}
  }
  const edit=<>
    {navigation&&createPortal(<div className="draft-dialog" role="dialog" aria-label="未保存修改"><p>范围尚未保存，是否保存后切换？</p><button disabled={busy||!valid} onClick={()=>void saveDraft().then(ok=>{if(ok){const go=navigation;setNavigation(null);go();}})}>保存并切换</button><button onClick={()=>{const go=navigation;discard();setNavigation(null);go();}}>放弃并切换</button><button onClick={()=>setNavigation(null)}>继续编辑</button></div>,document.body)}
    <section className="output-preset-section" aria-label="成片导出预设"><h3>导出预设</h3><ExportPresetControls draft={singleSettings.draft} onChange={singleSettings.change} saveOptions={{...singleSettings.draft.options,subtitle_settings:subtitleSettingsFromPlan(currentPlan)}} onApply={applyPreset} disabled={busy||historical||dirty||unsavedSubtitles||!singleSettings.loaded||!!singleSettings.loadError||singleSettings.saving||!!singleSettings.saveError} disabledReason={dirty||unsavedSubtitles?"先保存或放弃当前修改，再保存或应用预设。":historical?"历史版本只读，请切回当前版本后应用预设。":undefined}/><ExportDraftStatus state={singleSettings}/></section>
    <div className="edit-section-tabs" role="tablist" aria-label="编辑区域">
      {editSections.map(({id,label},index)=><button
        type="button" role="tab" key={id}
        id={editTabsId+"-tab-"+id} aria-controls={editTabsId+"-panel-"+id}
        aria-selected={editSection===id} tabIndex={editSection===id?0:-1}
        onClick={()=>setEditSection(id)}
        onKeyDown={event=>{
          let next=index;
          if(event.key==="ArrowRight")next=(index+1)%editSections.length;
          else if(event.key==="ArrowLeft")next=(index+editSections.length-1)%editSections.length;
          else if(event.key==="Home")next=0;
          else if(event.key==="End")next=editSections.length-1;
          else return;
          event.preventDefault();
          setEditSection(editSections[next].id);
          document.getElementById(editTabsId+"-tab-"+editSections[next].id)?.focus();
        }}
      >{label}{(id==="sentences"&&(dirty||sentenceDraft)||id==="hook"&&(dirty||hookDraft))&&<span className="edit-tab-unsaved">未保存</span>}</button>)}
    </div>
    <details className="edit-history"><summary>版本记录</summary><button disabled={busy||dirty} onClick={()=>{setHistoryError("");void getOutputVersions(project,collection,output).then(setVersions).catch(reason=>setHistoryError(reason instanceof Error?reason.message:"读取版本失败"));}}>查看版本</button>{historyError&&<p role="alert">{historyError}</p>}{versions.length>0&&<label>预览版本<select disabled={dirty} value={viewVersion??plan.revision} onChange={event=>setViewVersion(Number(event.target.value))}>{versions.map(version=><option key={version.revision} value={version.revision}>版本 {version.revision}</option>)}</select></label>}<p className="muted">历史只读，记录启用前的版本不可找回。</p></details>
    {((editSection==="sentences"||editSection==="hook")||dirty)&&<div className="draft-toolbar"><button className="primary-button" disabled={!dirty||busy||!valid} onClick={()=>void saveDraft()}>保存修改</button><button disabled={!undo.length||busy} onClick={()=>{setRedo([...redo,ranges]);setRanges(undo[undo.length-1]);setUndo(undo.slice(0,-1));}}>撤销</button><button disabled={!redo.length||busy} onClick={()=>{setUndo([...undo,ranges]);setRanges(redo[redo.length-1]);setRedo(redo.slice(0,-1));}}>重做</button><button disabled={!dirty||busy} onClick={discard}>放弃修改</button>{dirty&&<p role="status">范围未保存；保存会重新提取变更片段的字幕，并重置其已校正字幕及译文。</p>}{!valid&&<p role="alert">起止时间必须位于源素材内，且结束晚于开始。</p>}</div>}
    {actionError&&<p role="alert">{actionError}</p>}
    <section id={editTabsId+"-panel-frame"} role="tabpanel" aria-labelledby={editTabsId+"-tab-frame"} hidden={editSection!=="frame"}>
      <h3>作品画面设置</h3><p className="helper-text">作品预览和导出共用这些设置。</p>
      <OutputSettingsControls draft={singleSettings.draft} onChange={singleSettings.change} disabled={historical||!singleSettings.loaded||!!singleSettings.loadError} label="作品" sourceUrl={sourceUrl} sourceTime={sourceTime} showSubtitles={false}/>
      <ExportDraftStatus state={singleSettings}/><button type="button" onClick={()=>openEdit("subtitles")}>继续调整字幕</button>
    </section>
    <section id={editTabsId+"-panel-subtitles"} role="tabpanel" aria-labelledby={editTabsId+"-tab-subtitles"} hidden={editSection!=="subtitles"}>
      <label>字幕方式<select disabled={historical||!singleSettings.loaded||!!singleSettings.loadError} value={singleSettings.draft.options.subtitle_mode} onChange={event=>singleSettings.change({...singleSettings.draft,options:{...singleSettings.draft.options,subtitle_mode:event.target.value as ExportOptions["subtitle_mode"]}})}><option value="soft">软字幕（播放器可开关）</option><option value="burned">烧录字幕（画面内）</option></select></label>
      <p className="helper-text">排版设置仅用于烧录字幕；软字幕由播放器排版。</p><ExportDraftStatus state={singleSettings}/>{subtitleSettings}</section>
    <section id={editTabsId+"-panel-sentences"} role="tabpanel" aria-labelledby={editTabsId+"-tab-sentences"} hidden={editSection!=="sentences"}>
      {boundaryWarnings.length>0&&<details><summary>初始生成时的边界提示</summary>{boundaryWarnings.map(note=><p key={note} className="helper-text">{note}</p>)}<p className="helper-text">如果已调整范围，请以当前试听结果为准。</p></details>}
      <button disabled={busy||historical||dirty} onClick={()=>{if(!window.confirm("按转录句子拆分编辑片段，保留全部音视频和停顿；被拆分片段的字幕校正及译文将重置，可在历史版本中查看。继续？"))return;void update(()=>splitOutputSentences(project,collection,output,plan.revision)).catch(reason=>setActionError(String(reason)));}}>按句拆分片段</button>
      <details className="edit-guidance"><summary>编辑说明（范围、字幕与分句）</summary><p>范围调整可立即试听；统一点“保存修改”后会重新提取变更片段的字幕，并清除其已校正字幕和译文。相邻范围重叠会重复播放。</p><p>修改显示字幕不改变声音或时间；若有译文，也请同步核对。</p><p>手动分句时，在字幕中按句子或对话轮次换行，仅添加换行和标点，先预览时间再确认。分句依据原转录，建议试听；确认后生成新版本，但不渲染视频。</p><p>删除片段可恢复，作品至少保留一段正文。</p></details>
      <ol className="segments">{visibleClips.map((clip,index)=>clip.role==="body"?renderClip(clip,index):null)}</ol>
    </section>
    <section id={editTabsId+"-panel-hook"} role="tabpanel" aria-labelledby={editTabsId+"-tab-hook"} hidden={editSection!=="hook"}>
      <div className="hook-source-picker"><label>选择正文原话<select aria-label="选择预告原话" value={selectedHookSource?.instance_id??""} disabled={busy||historical||dirty||!selectedHookSource} onChange={event=>setHookSourceId(event.target.value)}>{hookCandidates.length===0&&<option value="">无可选片段</option>}{hookCandidates.map(clip=><option key={clip.instance_id} value={clip.instance_id}>{clip.text.slice(0,90)}</option>)}</select></label><button disabled={busy||historical||dirty||!selectedHookSource} onClick={()=>{if(selectedHookSource)changeRole(selectedHookSource,"hook");}}>复制为开场预告</button></div>
      <p className="helper-text">预告复制正文原话，正文保留。</p>
      <OutputOrderControls transitionKind={(visibleVersion??plan).hook_transition_kind??"fade"} transitionMs={(visibleVersion??plan).hook_transition_ms??300} clips={visibleClips} busy={busy||historical||dirty} save={(order,roles,transition,kind)=>update(()=>reorderOutput(project,collection,output,order,roles,transition,kind))} />
      {!visibleClips.some(clip=>clip.role==="hook")&&<p className="muted">当前没有开场预告。</p>}
      <ol className="segments">{visibleClips.map((clip,index)=>clip.role==="hook"?renderClip(clip,index):null)}</ol>
    </section>
  </>;
  const exportPanel=dirty?<p>请先保存或放弃范围修改后导出。</p>:historical?<p>切回当前版本后导出</p>:<OutputExport cover={<CoverEditor key={`cover:${collection}:${output}:${plan.revision}`} project={project} collection={collection} output={output} revision={plan.revision} clips={plan.clips} onDirty={setCoverDirty} onSaved={setCoverVersion} />} disabled={coverDirty||coverVersion===undefined||unsavedSubtitles} disabledReason={unsavedSubtitles?"先保存字幕修改，再导出。":undefined} coverVersion={coverVersion} onAdjust={openEdit} key={`${collection}:${output}:${plan.revision}`} project={project} collection={collection} output={output} revision={plan.revision} onSubmitted={onExportSubmitted} />;
  return compose?compose({preview,edit,exportPanel}):<Workbench tab={localPanel} onTabChange={setLocalPanel} sidebar={<><h2>当前作品</h2><p>{plan.title}</p><details><summary>选材理由</summary><p>{plan.reason}</p></details><a href={`?project=${encodeURIComponent(project)}`}>返回候选列表</a></>} preview={preview} generate={<p>返回候选列表以生成新作品</p>} edit={edit} exportPanel={exportPanel} />;
}
