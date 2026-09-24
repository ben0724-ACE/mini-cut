import type { HighlightResult } from "./api";

function distinct(values: string[]): string[] {
  return [...new Set(values.map(value => value.trim()).filter(Boolean))];
}

export function outputBoundaryWarnings(notes: string[], title: string): string[] {
  return distinct(notes.filter(note => note.startsWith(`${title}：`) && note.includes("建议检查开头／结尾")).map(note => note.slice(title.length + 1)));
}

export function generationDetails(result: HighlightResult) {
  const outputs = result.outputs;
  const missingHooks = result.brief.hook_ms == null ? 0 : outputs.filter(output => !output.clips.some(clip => clip.role === "hook" && !clip.deleted)).length;
  const boundaryWarnings = distinct(result.notes.filter(note => note.includes("建议检查开头／结尾") || note.includes("句界复核未完成")));
  const explanations: string[] = [];
  for (const note of result.notes) {
    if (/^(数量不足：|句界复核后保留)/.test(note)) continue;
    if (/：(?:未找到独立原话钩子|未确认独立短句|完整内容略超目标时长)/.test(note)) continue;
    if (boundaryWarnings.includes(note)) continue;
    if (/候选(?:为连续正文|约\d+(?:\.\d+)?秒)/.test(note)) continue;
    const shortage = note.match(/^仅返回\d+条候选，未凑足brief\.count=\d+[:：](.*)$/);
    const hook = note.match(/^.*候选均未找到[^：]*钩子[:：](.*)$/);
    if (shortage) explanations.push(`候选不足原因：${shortage[1].trim()}`);
    else if (hook) explanations.push(`钩子原因：${hook[1].trim().replace(/，?故hook_segment_ids均留空。?$/, "。").replace(/(\d+)–(\d+) ms/g, (_, low: string, high: string) => `${Number(low) / 1000}–${Number(high) / 1000} 秒`)}`);
    else explanations.push(note);
  }
  return { missingHooks, boundaryWarnings, explanations: distinct(explanations) };
}

export function GenerationDetails({assetName, result}: {assetName: string; result: HighlightResult}) {
  const {missingHooks, boundaryWarnings, explanations} = generationDetails(result);
  const target = result.brief.count;
  return <details className="generation-details"><summary>生成详情</summary>
    <p>源素材：{assetName}</p>
    <p>已生成 {result.outputs.length} / {target} 条候选{result.outputs.length < target ? "；未用不完整片段凑数" : ""}。</p>
    {result.outputs.length > 0 && <ul>{result.outputs.map(output => <li key={output.output_id}>{output.title} · {(output.duration_ms / 1000).toFixed(1)} 秒{result.brief.hook_ms != null ? output.clips.some(clip => clip.role === "hook" && !clip.deleted) ? " · 含开场钩子" : " · 无开场钩子" : ""}</li>)}</ul>}
    {missingHooks > 0 && <p>钩子：{missingHooks} 条未找到符合时长和完整原话要求的内容；可在编辑页试听并手动调整。</p>}
    {boundaryWarnings.length > 0 && <section><h3>需要检查</h3><ul>{boundaryWarnings.map(note => <li key={note}>{note}</li>)}</ul></section>}
    {explanations.length > 0 && <section><h3>选材说明</h3><ul>{explanations.map(note => <li key={note}>{note}</li>)}</ul></section>}
  </details>;
}
