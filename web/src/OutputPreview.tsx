import { useEffect, useRef, useState } from "react";
import type { HighlightClip } from "./api";

export function OutputPreview({title, mediaUrl, clips: allClips, jumpTo}: {title:string; mediaUrl:string; clips:HighlightClip[]; jumpTo?: {ms: number; sequence: number}}) {
  const clips = allClips.filter(clip => !clip.deleted);
  const video = useRef<HTMLVideoElement>(null); const cursor = useRef<number | null>(null);
  const [error, setError] = useState("");
  const [caption, setCaption] = useState("");
  useEffect(() => {if (jumpTo && video.current) {cursor.current = null; video.current.pause(); video.current.currentTime = jumpTo.ms / 1000; setCaption(allClips.find(clip => clip.start_ms === jumpTo.ms)?.text ?? "");}}, [jumpTo]);
  return <div><video aria-label={`播放器 · ${title}`} ref={video} className="player" controls preload="metadata" src={mediaUrl} onPlay={() => {document.querySelectorAll("video").forEach(other => {if (other !== video.current) other.pause();});}} onError={() => setError("媒体无法加载")} onTimeUpdate={() => {
    const player = video.current; const index = cursor.current;
    if (player) setCaption(clips.find(clip => player.currentTime * 1000 >= clip.start_ms && player.currentTime * 1000 < clip.end_ms)?.text ?? "");
    if (!player || index === null) return;
    const clip = clips[index];
    if (player.currentTime * 1000 < clip.end_ms) return;
    const next = clips[index + 1];
    if (next) {cursor.current = index + 1; player.currentTime = next.start_ms / 1000;}
    else {cursor.current = null; player.pause();}
  }} /><p className="preview-caption" aria-label="当前字幕">{caption}</p><button disabled={!clips.length} onClick={() => {
    const player = video.current; if (!player || !clips[0]) return;
    setError(""); cursor.current = 0; player.currentTime = clips[0].start_ms / 1000;
    void player.play().catch(() => {cursor.current = null; setError("播放失败，请检查媒体或重试");});
  }}>预览{title}</button>{error && <p role="alert">{error}</p>}<p>按计划跳转源视频的实时预览，并非已导出成片；切点精度受浏览器播放事件限制。</p></div>;
}
