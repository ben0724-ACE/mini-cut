import { useEffect, useRef, useState } from "react";
import { navigateWithDraft } from "./draftNavigation";
import { listAssets, uploadAsset, type AssetDetail } from "./api";
import { TranscriptionControls } from "./TranscriptionControls";
import { HighlightPanel } from "./HighlightPanel";

interface Props {projectId:string;onOpen:(asset:string)=>void;load?:typeof listAssets;upload?:typeof uploadAsset}
export function AssetLibrary({projectId,onOpen,load=listAssets,upload=uploadAsset}:Props) {
  const [assets,setAssets]=useState<AssetDetail[]|null>(null);const [selected,setSelected]=useState("");
  const fileInput=useRef<HTMLInputElement>(null);
  const [file,setFile]=useState<File|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [retry,setRetry]=useState(0);
  useEffect(()=>{const controller=new AbortController();setError("");load(projectId,controller.signal).then(value=>{if(!controller.signal.aborted)setAssets(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:"无法读取素材");});return()=>controller.abort();},[projectId,load,retry]);
  async function submit(){if(!file||busy)return;setBusy(true);setError("");try{const imported=await upload(projectId,file);setAssets(await load(projectId));setSelected(imported.asset_id);}catch(reason){setError(reason instanceof Error?reason.message:"导入失败");}finally{setBusy(false);}}
  const asset=assets?.find(asset=>asset.asset_id===selected)??assets?.[0];
  const assetHeader=asset&&<div className="asset-context-bar"><label>当前素材<select aria-label="当前素材" value={asset.asset_id} onChange={event=>{const value=event.target.value;navigateWithDraft(()=>setSelected(value));}}>{assets?.map(item=><option key={item.asset_id} value={item.asset_id}>{item.name}</option>)}</select></label><span className="muted">{(asset.duration_ms/60_000).toFixed(1)} 分钟 · {asset.has_transcript?"已转录":"未转录"}</span>{asset.has_plan&&<button onClick={()=>onOpen(asset.asset_id)}>审阅现有剪辑</button>}</div>;
  const transcription=asset&&<details className="transcription-disclosure" open={!asset.has_transcript}><summary>转录设置 · {asset.has_transcript?"已完成":"待转录"}</summary><TranscriptionControls project={projectId} asset={asset.asset_id} onComplete={()=>setRetry(value=>value+1)} /></details>;
  return <section aria-label="素材库"><div className="import-bar"><details open={assets?.length===0?true:undefined}><summary>添加素材</summary><div className="import-actions"><input ref={fileInput} className="import-file-input" aria-hidden="true" type="file" accept=".mp4,.mov,.mkv,.avi,.flv,.f4v,.webm,.ogg,.wav,.mp3,.flac,.m4a" tabIndex={-1} disabled={busy} onChange={event=>setFile(event.target.files?.[0]??null)} /><button type="button" disabled={busy} onClick={()=>fileInput.current?.click()}>选择本地文件</button><span className="muted">{file?.name??"未选择文件"}</span><button type="button" disabled={!file||busy} onClick={()=>void submit()}>{busy?"正在导入…":"导入选中文件"}</button></div><p className="muted">复制到本地项目，不上传到 LLM；保留原视频。</p></details>{!!assets?.length&&<span className="muted">素材 {assets.length}</span>}{busy&&<span role="status">正在传输和分析</span>}</div>{error&&<p role="alert">{error}<button onClick={()=>{setError("");setRetry(value=>value+1);}}>重新读取列表</button></p>}{assets===null&&!error?<p role="status">正在读取素材…</p>:asset?<>{assetHeader}<HighlightPanel key={asset.asset_id} project={projectId} asset={asset} transcription={transcription} /></>:null}</section>;
}
