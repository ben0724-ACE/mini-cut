import { useEffect, useRef, useState } from "react";
import type { HighlightClip } from "./api";
export interface Audition {id:string; part:"start"|"end"|"whole"; sequence:number}
export function QuickPreview({sourceUrl,title,clips,audition,playSequence,onDuration,compact=false}:{sourceUrl:string;title:string;clips:HighlightClip[];audition?:Audition;playSequence?:number;onDuration:(ms:number)=>void;compact?:boolean}) {
  const video=useRef<HTMLVideoElement>(null);
  const queue=useRef<{start:number;end:number}[]>([]);
  const all=useRef(false);
  const index=useRef(0); const [error,setError]=useState("");
  function begin(ranges:{start:number;end:number}[]) {
    queue.current=ranges;index.current=0;setError("");
    if(!ranges.length){setError("此切点附近没有可播放的保留内容");return;}
    if(video.current&&video.current.readyState>=1)startQueuedPlayback();
  }
  function startQueuedPlayback(){
    const element=video.current;const current=queue.current[index.current];if(!element||!current)return;
    document.querySelectorAll("video").forEach(other=>{if(other!==element&&!other.paused)other.pause();});
    element.currentTime=current.start/1000;
    void element.play().catch(()=>setError("点击播放器播放按钮开始试听"));
  }
  useEffect(()=>{if(playSequence===undefined)return;all.current=true;begin(clips.filter(c=>!c.deleted).map(c=>({start:c.start_ms,end:c.end_ms})));},[playSequence]);
  useEffect(()=>{
    if(!audition)return;
    const clip=clips.find(c=>c.instance_id===audition.id);if(!clip)return;
    all.current=false;begin([{start:audition.part==="end"?Math.max(clip.start_ms,clip.end_ms-3000):clip.start_ms,end:audition.part==="start"?Math.min(clip.end_ms,clip.start_ms+3000):clip.end_ms}]);
  },[audition]); // Edits update the active interval below without restarting playback.
  useEffect(()=>{if(all.current&&queue.current.length){queue.current=clips.filter(c=>!c.deleted).map(c=>({start:c.start_ms,end:c.end_ms}));const current=queue.current[index.current];if(video.current&&current&&video.current.currentTime*1000<current.start)video.current.currentTime=current.start/1000;}else if(audition&&queue.current.length===1){const clip=clips.find(c=>c.instance_id===audition.id);if(clip){queue.current=[{start:audition.part==="end"?Math.max(clip.start_ms,clip.end_ms-3000):clip.start_ms,end:audition.part==="start"?Math.min(clip.end_ms,clip.start_ms+3000):clip.end_ms}];if(video.current&&video.current.currentTime*1000<queue.current[0].start)video.current.currentTime=queue.current[0].start/1000;}}},[clips,audition]);
  function tick(){const element=video.current;const current=queue.current[index.current];if(!element||!current)return;if(element.currentTime*1000>=current.end){index.current++;const next=queue.current[index.current];if(next){if(next.start!==current.end)element.currentTime=next.start/1000;}else{element.pause();element.currentTime=current.end/1000;queue.current=[];}}}
  useEffect(()=>{let frame=0;const run=()=>{tick();frame=requestAnimationFrame(run);};frame=requestAnimationFrame(run);return()=>cancelAnimationFrame(frame);},[]);
  return <div className={`quick-preview ${compact?"is-compact":""}`}>{!compact&&<p className="muted">源视频 · 范围修改即时生效</p>}<video ref={video} className="player" controls preload="metadata" src={sourceUrl} aria-label={`快速预览 · ${title}`} onLoadedMetadata={()=>{if(video.current){onDuration(Math.round(video.current.duration*1000));if(queue.current.length)startQueuedPlayback();}}} onTimeUpdate={tick} onPlay={()=>{if(!queue.current.length){const clip=clips.find(c=>c.instance_id===audition?.id)??clips.find(c=>!c.deleted);if(clip&&video.current){queue.current=[{start:clip.start_ms,end:clip.end_ms}];index.current=0;all.current=false;if(video.current.currentTime*1000<clip.start_ms||video.current.currentTime*1000>=clip.end_ms)video.current.currentTime=clip.start_ms/1000;}}}} onError={()=>setError("源素材无法播放")} /><button onClick={()=>{all.current=true;begin(clips.filter(c=>!c.deleted).map(c=>({start:c.start_ms,end:c.end_ms})));}}>播放全部片段</button>{!compact&&<p className="helper-text">字幕和转场需生成成片预览；切换片段可能短暂停顿。</p>}{error&&<p role="status">{error}</p>}</div>;
}
