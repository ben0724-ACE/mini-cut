import {useEffect,useState} from "react";
import type {HighlightClip} from "./api";
import {SaveStatus,type SaveState} from "./SaveStatus";
interface Props {clips:HighlightClip[];busy:boolean;transitionMs?:number;transitionKind?:string;save:(order:string[],roles:Record<string,string>,transitionMs?:number,transitionKind?:string)=>Promise<void>;onStatus?:(status:SaveState)=>void}
export function OutputOrderControls({clips,busy,save,transitionMs=300,transitionKind="fade",onStatus}:Props){
  const [desired,setDesired]=useState({ms:transitionMs,kind:transitionKind}),[saving,setSaving]=useState(false),[error,setError]=useState("");
  const dirty=desired.ms!==transitionMs||desired.kind!==transitionKind;
  useEffect(()=>{setDesired({ms:transitionMs,kind:transitionKind});},[transitionMs,transitionKind]);
  useEffect(()=>{onStatus?.(saving?"saving":dirty?"dirty":undefined);return()=>onStatus?.(undefined);},[dirty,saving,onStatus]);
  async function update(next:typeof desired){setDesired(next);setError("");setSaving(true);try{await save(clips.map(c=>c.instance_id),{},next.ms,next.kind);}catch(reason){setError(reason instanceof Error?reason.message:"保存失败");}finally{setSaving(false);}}
  return <details><summary>开场转场设置 <SaveStatus dirty={dirty} saving={saving}/></summary>
    <label>转场效果<select value={desired.kind} disabled={busy||saving} onChange={event=>void update({...desired,kind:event.target.value})}><option value="fade">渐隐后渐入</option><option value="tv_static">电视花屏＋哔声</option></select></label>
    <label>{desired.kind==="fade"?"开场预告转场时长（渐出、渐入各自时长）":"花屏与哔声时长"}<select value={desired.ms} disabled={busy||saving} onChange={event=>void update({...desired,ms:Number(event.target.value)})}>{[0,150,300,500,1000].map(ms=><option key={ms} value={ms}>{ms===0?"无转场":`${ms/1000} 秒`}</option>)}</select></label>
    <p className="muted">{desired.kind==="fade"?"极短片段会自动缩短渐变。":"在预告与正文之间插入此时长的花屏，不覆盖讲话，正文字幕同步顺延。"}没有开场预告时不应用；选无转场可关闭。更改自动保存为新版本。</p>
    {error&&<p role="alert">{error} <button disabled={busy||saving} onClick={()=>void update(desired)}>重试保存转场</button><button disabled={busy||saving} onClick={()=>{setDesired({ms:transitionMs,kind:transitionKind});setError("");}}>放弃转场修改</button></p>}
  </details>;
}
