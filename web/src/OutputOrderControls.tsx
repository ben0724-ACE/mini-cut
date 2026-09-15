import { useState } from "react";
import type { HighlightClip } from "./api";

interface Props {
  clips: HighlightClip[];
  busy: boolean;
  transitionMs?: number;
  showItems?: boolean;
  transitionKind?: string;
  save: (order: string[], roles: Record<string, string>, transitionMs?: number, transitionKind?:string) => Promise<void>;
}

export function OutputOrderControls({ clips, busy, save, transitionMs = 300, showItems = true, transitionKind = "fade" }: Props) {
  const [error, setError] = useState("");

  async function update(order: string[], roles: Record<string, string> = {}, transition?: number, kind?:string) {
    setError("");
    try {
      if (kind !== undefined) await save(order, roles, transitionMs, kind);
      else if (transition === undefined) await save(order, roles);
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
    <summary>开场转场设置</summary>
    <p>开场预告复制原话，正文保留完整片段；在下方每个片段中调整范围、字幕与顺序。</p><label>转场效果<select value={transitionKind} disabled={busy} onChange={event=>void update(clips.map(c=>c.instance_id),{},undefined,event.target.value)}><option value="fade">渐隐后渐入</option><option value="tv_static">电视花屏＋哔声</option></select></label>
    <label>{transitionKind === "fade" ? "钩子转场时长（渐出、渐入各自时长）" : "花屏与哔声时长"}
      <select value={transitionMs} disabled={busy} onChange={event => void update(clips.map(clip => clip.instance_id), {}, Number(event.target.value))}>
        {[0, 150, 300, 500, 1000].map(ms => <option key={ms} value={ms}>{ms === 0 ? "无转场" : `${ms / 1000} 秒`}</option>)}
      </select>
    </label>
    <p className="muted">{transitionKind === "fade" ? "极短片段会自动缩短渐变。" : "在预告与正文之间插入此时长的花屏，不覆盖讲话，正文字幕同步顺延。"}没有开场预告时不应用；选无转场可关闭。更改自动保存为新版本。</p>
    {showItems && clips.map((clip, index) => <div key={clip.instance_id}>
      <span>{clip.text}（{clip.role}）</span>
      <button aria-label={`上移 ${clip.instance_id}`} disabled={busy || index === 0} onClick={() => move(index, -1)}>上移</button>
      <button aria-label={`下移 ${clip.instance_id}`} disabled={busy || index === clips.length - 1} onClick={() => move(index, 1)}>下移</button>
      <button disabled={busy} onClick={() => toggleHook(clip)}>{clip.role === "hook" ? "取消开场预告" : "添加为开场预告"}</button>
    </div>)}
    {error && <p role="alert">{error}</p>}
  </details>;
}
