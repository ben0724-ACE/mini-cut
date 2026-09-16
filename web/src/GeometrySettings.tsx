import { useState } from "react";
export interface GeometryOptions {aspect_ratio:"original"|"16:9"|"9:16"|"1:1"|"4:5"; resolution:720|1080; fit:"pad"|"crop";crop_left?:number;crop_right?:number;crop_top?:number;crop_bottom?:number}
export const defaultGeometry:GeometryOptions={aspect_ratio:"original",resolution:1080,fit:"pad"};
export function GeometrySettings({value,onChange,disabled=false,label="导出",sourceUrl,sourceTime=0}:{value:Partial<GeometryOptions>;onChange:(value:GeometryOptions)=>void;disabled?:boolean;label?:string;sourceUrl?:string;sourceTime?:number}) {
  const [dimensions,setDimensions]=useState({width:16,height:9});
  const current={...defaultGeometry,...value};
  const left=current.crop_left??0,right=current.crop_right??0,top=current.crop_top??0,bottom=current.crop_bottom??0;
  const cropped=left+right+top+bottom>0;
  return <fieldset disabled={disabled}><legend>{label}画幅</legend>
    <label>{label}比例<select value={current.aspect_ratio} onChange={event=>onChange({...current,aspect_ratio:event.target.value as GeometryOptions["aspect_ratio"]})}>{["original","16:9","9:16","1:1","4:5"].map(ratio=><option key={ratio} value={ratio}>{ratio==="original"?"原始比例":ratio}</option>)}</select></label>
    <label>{label}分辨率<select value={current.resolution} onChange={event=>onChange({...current,resolution:Number(event.target.value) as GeometryOptions["resolution"]})}><option value={720}>720 档</option><option value={1080}>1080 档</option></select></label>
    <label>{label}适配<select value={current.fit} onChange={event=>onChange({...current,fit:event.target.value as GeometryOptions["fit"]})}><option value="pad">完整加边框</option><option value="crop">居中裁切</option></select></label>
    <details><summary>自由裁剪画面</summary><p className="helper-text">分别裁去上下左右边缘。保持「原始比例」时，导出长宽跟随裁剪区域；选择固定比例后再进行适配。</p>
    <div className="clip-boundaries">{([['crop_top','上'],['crop_bottom','下'],['crop_left','左'],['crop_right','右']] as const).map(([key,title])=><label key={key}>{label}裁去{title}侧（%）<input type="number" min={0} max={95} step={0.5} value={current[key]??0} onChange={event=>{const value=Number(event.target.value);const opposite=key==='crop_top'?bottom:key==='crop_bottom'?top:key==='crop_left'?right:left;onChange({...current,[key]:Math.min(95-opposite,Math.max(0,Number.isFinite(value)?value:0))});}} /></label>)}</div>
    <button type="button" disabled={disabled||!cropped} onClick={()=>onChange({...current,crop_left:0,crop_right:0,crop_top:0,crop_bottom:0})}>重置裁剪</button>
    <div className="crop-preview" style={{aspectRatio:`${dimensions.width}/${dimensions.height}`}}>
      {sourceUrl?<video muted controls preload="metadata" src={sourceUrl} aria-label={`${label}裁剪参考画面`} onLoadedMetadata={event=>{const video=event.currentTarget;setDimensions({width:video.videoWidth||16,height:video.videoHeight||9});video.currentTime=sourceTime;}} />:<span className="helper-text">原始画面示意</span>}
      <div className="crop-outline" style={{left:`${left}%`,right:`${right}%`,top:`${top}%`,bottom:`${bottom}%`}} />
    </div><p className="helper-text">亮框为保留区域，暗区将被裁掉。保留宽 {(100-left-right).toFixed(1)}% × 高 {(100-top-bottom).toFixed(1)}%。{sourceUrl?'':'示意图不代表素材实际比例。'}裁剪不改变视频时长或声音；源画面已有字幕也会一起裁剪。</p></details>
    <p className="helper-text">居中裁切可能裁掉边缘人物或源字幕。</p>
    <details><summary>画幅说明</summary><p className="helper-text">保持比例，不拉伸、不追踪人物。原始比例不放大；720 / 1080 档最长边上限为 1280 / 1920。</p></details>
  </fieldset>;
}
