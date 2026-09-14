import { useState } from "react";
import type { HighlightClip } from "./api";

interface Props {
  clips: HighlightClip[];
  busy: boolean;
  transitionMs?: number;
  save: (order: string[], roles: Record<string, string>, transitionMs?: number) => Promise<void>;
}

export function OutputOrderControls({ clips, busy, save, transitionMs = 300 }: Props) {
  const [error, setError] = useState("");

  async function update(order: string[], roles: Record<string, string> = {}, transition?: number) {
    setError("");
    try {
      if (transition === undefined) await save(order, roles);
      else await save(order, roles, transition);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    }
  }

  function move(index: number, offset: number) {
    const order = clips.map(clip => clip.instance_id);
    [order[index + offset], order[index]] = [order[index], order[index + offset]];
    void update(order);
  }

  function toggleHook(clip: HighlightClip) {
    const role = clip.role === "hook" ? "body" : "hook";
    const rank = (item: HighlightClip) => (item.instance_id === clip.instance_id ? role : item.role) === "hook" ? 0 : 1;
    const ordered = [...clips].sort((a, b) => rank(a) - rank(b));
    void update(ordered.map(item => item.instance_id), { [clip.instance_id]: role });
  }

  return <details>
    <summary>片段顺序与开场原话</summary>
    <p>开场预告复制原话，正片保留完整片段和原顺序；预告结束渐隐，再渐入正片。不生成新语音。</p>
    <label>钩子转场时长（渐出、渐入各自时长）
      <select value={transitionMs} disabled={busy} onChange={event => void update(clips.map(clip => clip.instance_id), {}, Number(event.target.value))}>
        {[0, 150, 300, 500, 1000].map(ms => <option key={ms} value={ms}>{ms === 0 ? "无转场" : `${ms / 1000} 秒`}</option>)}
      </select>
    </label>
    <p className="muted">极短片段会自动缩短转场；没有开场预告时不应用。更改自动保存为新版本。</p>
    {clips.map((clip, index) => <div key={clip.instance_id}>
      <span>{clip.text}（{clip.role}）</span>
      <button aria-label={`上移 ${clip.instance_id}`} disabled={busy || index === 0} onClick={() => move(index, -1)}>上移</button>
      <button aria-label={`下移 ${clip.instance_id}`} disabled={busy || index === clips.length - 1} onClick={() => move(index, 1)}>下移</button>
      <button disabled={busy} onClick={() => toggleHook(clip)}>{clip.role === "hook" ? "取消开场预告" : "添加为开场预告"}</button>
    </div>)}
    {error && <p role="alert">{error}</p>}
  </details>;
}
