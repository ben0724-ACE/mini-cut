import { useEffect, useRef, useState } from "react";
import type { HighlightClip } from "./api";
export interface Audition {id:string; part:"start"|"end"|"whole"; sequence:number}
export function QuickPreview({sourceUrl,title,clips,audition,onDuration}:{sourceUrl:string;title:string;clips:HighlightClip[];audition?:Audition;onDuration:(ms:number)=>void}) {
  const video=useRef<HTMLVideoElement>(null);
  const queue=useRef<{start:number;end:number}[]>([]);
  const all=useRef(false);
  const index=useRef(0); const [error,setError]=useState("");
  function begin(ranges:{start:number;end:number}[]) {
    queue.current=ranges;index.current=0;setError("");
    if(video.current&&ranges.length){video.current.currentTime=ranges[0].start/1000;void video.current.play().catch(()=>setError("点击播放器播放按钮开始试听"));}
  }
  useEffect(()=>{
    if(!audition)return;
    const clip=clips.find(c=>c.instance_id===audition.id);if(!clip)return;
    all.current=false;begin([{start:audition.part==="end"?Math.max(clip.start_ms,clip.end_ms-3000):clip.start_ms,end:audition.part==="start"?Math.min(clip.end_ms,clip.start_ms+3000):clip.end_ms}]);
  },[audition]); // Edits update the active interval below without restarting playback.
  useEffect(()=>{if(all.current&&queue.current.length){queue.current=clips.filter(c=>!c.deleted).map(c=>({start:c.start_ms,end:c.end_ms}));const current=queue.current[index.current];if(video.current&&current&&video.current.currentTime*1000<current.start)video.current.currentTime=current.start/1000;}else if(audition&&queue.current.length===1){const clip=clips.find(c=>c.instance_id===audition.id);if(clip){queue.current=[{start:audition.part==="end"?Math.max(clip.start_ms,clip.end_ms-3000):clip.start_ms,end:audition.part==="start"?Math.min(clip.end_ms,clip.start_ms+3000):clip.end_ms}];if(video.current&&video.current.currentTime*1000<queue.current[0].start)video.current.currentTime=queue.current[0].start/1000;}}},[clips,audition]);
  function tick(){const element=video.current;const current=queue.current[index.current];if(!element||!current)return;if(element.currentTime*1000>=current.end){index.current++;const next=queue.current[index.current];if(next){if(next.start!==current.end)element.currentTime=next.start/1000;}else{element.pause();element.currentTime=current.end/1000;queue.current=[];}}}
  useEffect(()=>{let frame=0;const run=()=>{tick();frame=requestAnimationFrame(run);};frame=requestAnimationFrame(run);return()=>cancelAnimationFrame(frame);},[]);
  return <div><p className="muted">快速预览 · 源素材直接播放 · 范围调整即时生效</p><video ref={video} className="player" controls preload="metadata" src={sourceUrl} aria-label={`快速预览 · ${title}`} onLoadedMetadata={()=>{if(video.current)onDuration(Math.round(video.current.duration*1000));}} onTimeUpdate={tick} onPlay={()=>{if(!queue.current.length){const clip=clips.find(c=>c.instance_id===audition?.id)??clips.find(c=>!c.deleted);if(clip&&video.current){queue.current=[{start:clip.start_ms,end:clip.end_ms}];index.current=0;all.current=false;if(video.current.currentTime*1000<clip.start_ms||video.current.currentTime*1000>=clip.end_ms)video.current.currentTime=clip.start_ms/1000;}}}} onError={()=>setError("源素材无法播放")} /><button onClick={()=>{all.current=true;begin(clips.filter(c=>!c.deleted).map(c=>({start:c.start_ms,end:c.end_ms})));}}>播放全部片段</button><p className="helper-text">快速预览不烧录字幕或转场；片段间跳转可能短暂停顿，最终效果请生成成片预览。</p>{error&&<p role="status">{error}</p>}</div>;
}
