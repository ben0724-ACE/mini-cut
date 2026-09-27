import type { HighlightOutput, HighlightResult } from "./api";

function distinct(values: string[]): string[] {
  return [...new Set(values.map(value => value.trim()).filter(Boolean))];
}

function formatSeconds(milliseconds: number): string {
  return String(Number((milliseconds / 1000).toFixed(2)));
}

function openingPreviewBounds(targetMs: number): [number, number] {
  return [
    Math.max(500, targetMs - Math.min(3000, Math.floor(targetMs * 2 / 5))),
    targetMs + Math.min(3000, Math.floor(targetMs * 3 / 5)),
  ];
}

function openingPreviewDuration(output: HighlightOutput): number | null {
  const ranges = output.clips
    .filter(clip => clip.role === "hook" && !clip.deleted && clip.end_ms > clip.start_ms)
    .map(clip => [clip.start_ms, clip.end_ms] as [number, number])
    .sort((left, right) => left[0] - right[0]);
  if (!ranges.length) return null;
  let duration = 0;
  let [start, end] = ranges[0];
  for (const [nextStart, nextEnd] of ranges.slice(1)) {
    if (nextStart <= end) end = Math.max(end, nextEnd);
    else {
      duration += end - start;
      [start, end] = [nextStart, nextEnd];
    }
  }
  return duration + end - start;
}

function displayOpeningPreviewNote(note: string): string {
  return note
    .replaceAll("初选钩子", "初选开场预告")
    .replaceAll("钩子", "开场预告")
    .replace(/，?故hook_segment_ids均留空。?$/, "。")
    .replace(/(\d+)–(\d+) ms/g, (_, low: string, high: string) => `${Number(low) / 1000}–${Number(high) / 1000} 秒`);
}

export interface OpeningPreviewTrace {
  outputId: string;
  title: string;
  finalDurationMs: number | null;
  finalWithinBounds: boolean | null;
  steps: string[];
}

function openingPreviewTrace(output: HighlightOutput, notes: string[], bounds: [number, number]): OpeningPreviewTrace {
  const [low, high] = bounds;
  const finalDurationMs = openingPreviewDuration(output);
  const finalWithinBounds = finalDurationMs == null ? null : low <= finalDurationMs && finalDurationMs <= high;
  const ownNotes = notes.filter(note => note.startsWith(`${output.title}：`)).map(note => note.slice(output.title.length + 1));
  const rejected = ownNotes.map(note => note.match(/初选钩子未通过：实测\s*(\d+(?:\.\d+)?)\s*秒，不在允许的\s*(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)\s*秒范围内/)).find(Boolean);
  const retainedInitial = ownNotes.some(note => note.includes("词级复核未提供有效替代钩子，保留初选已校验的完整原话"));
  const noConfirmedReplacement = ownNotes.some(note => note.includes("未确认独立短句，不添加钩子"));
  const noInitial = ownNotes.some(note => note.includes("未找到独立原话钩子"));
  const steps: string[] = [];

  if (rejected) {
    steps.push(`AI 初选：选出 ${rejected[1]} 秒的开场预告。`);
    steps.push(`本地校验：未通过，不在 ${rejected[2]}–${rejected[3]} 秒允许范围内，初选结果被淘汰。`);
    if (finalDurationMs != null) {
      steps.push(`词级复核：重新选出 ${formatSeconds(finalDurationMs)} 秒的完整原话。`);
    } else if (noConfirmedReplacement || noInitial) {
      steps.push("词级复核：没有找到符合范围且语义完整的替代内容。");
    } else {
      steps.push("词级复核：没有形成可采用的替代结果。");
    }
  } else if (retainedInitial && finalDurationMs != null) {
    steps.push(`AI 初选：选出 ${formatSeconds(finalDurationMs)} 秒的开场预告。`);
    steps.push(`本地校验：通过，位于 ${formatSeconds(low)}–${formatSeconds(high)} 秒允许范围内。`);
    steps.push("词级复核：没有提供更合适的有效替代，保留已通过校验的初选原话。");
  } else if (finalDurationMs != null) {
    steps.push("AI 初选：单独的初选记录未保存，无法还原初选时长。");
    steps.push(`词级复核：确认当前 ${formatSeconds(finalDurationMs)} 秒的完整原话。`);
  } else {
    steps.push(noInitial ? "AI 初选：没有保留符合要求的独立原话。" : "AI 初选：单独的初选记录未保存。");
    steps.push(noConfirmedReplacement ? "词级复核：仍未确认符合要求的独立完整原话。" : "复核：没有形成可采用的开场预告。");
  }

  if (finalDurationMs == null) {
    steps.push("最终结果：不添加开场预告，保留完整正文。");
  } else if (finalWithinBounds) {
    steps.push(`最终结果：采用 ${formatSeconds(finalDurationMs)} 秒开场预告，符合 ${formatSeconds(low)}–${formatSeconds(high)} 秒范围。`);
  } else {
    steps.push(`最终结果：当前保存的开场预告为 ${formatSeconds(finalDurationMs)} 秒，不在 ${formatSeconds(low)}–${formatSeconds(high)} 秒范围内，建议试听检查。`);
  }
  return {outputId: output.output_id, title: output.title, finalDurationMs, finalWithinBounds, steps};
}

export function outputBoundaryWarnings(notes: string[], title: string): string[] {
  return distinct(notes.filter(note => note.startsWith(`${title}：`) && note.includes("建议检查开头／结尾")).map(note => note.slice(title.length + 1)));
}

export function generationDetails(result: HighlightResult) {
  const outputs = result.outputs;
  const bounds = result.brief.hook_ms == null ? null : openingPreviewBounds(result.brief.hook_ms);
  const openingPreviewTraces = bounds ? outputs.map(output => openingPreviewTrace(output, result.notes, bounds)) : [];
  const missingOpeningPreviews = openingPreviewTraces.filter(trace => trace.finalDurationMs == null).length;
  const boundaryWarnings = distinct(result.notes.filter(note => note.includes("建议检查开头／结尾") || note.includes("句界复核未完成")));
  const explanations: string[] = [];
  const openingPreviewNotes: string[] = [];
  for (const note of result.notes) {
    if (/^(数量不足：|句界复核后保留)/.test(note)) continue;
    if (boundaryWarnings.includes(note)) continue;
    if (/候选(?:为连续正文|约\d+(?:\.\d+)?秒)/.test(note)) continue;
    if (/(?:钩子|hook_segment_ids)/.test(note)) {
      if (!outputs.some(output => note.startsWith(`${output.title}：`))) openingPreviewNotes.push(displayOpeningPreviewNote(note));
      continue;
    }
    const shortage = note.match(/^仅返回\d+条候选，未凑足brief\.count=\d+[:：](.*)$/);
    if (shortage) explanations.push(`候选不足原因：${shortage[1].trim()}`);
    else explanations.push(note);
  }
  return {
    bounds,
    missingOpeningPreviews,
    boundaryWarnings,
    openingPreviewTraces,
    openingPreviewNotes: distinct(openingPreviewNotes),
    explanations: distinct(explanations),
  };
}

export function GenerationDetails({assetName, result}: {assetName: string; result: HighlightResult}) {
  const {bounds, missingOpeningPreviews, boundaryWarnings, openingPreviewTraces, openingPreviewNotes, explanations} = generationDetails(result);
  const target = result.brief.count;
  const generatedOpeningPreviews = openingPreviewTraces.length - missingOpeningPreviews;
  return <details className="generation-details"><summary>生成详情</summary>
    <p>源素材：{assetName}</p>
    <p>已生成 {result.outputs.length} / {target} 条候选{result.outputs.length < target ? "；未用不完整片段凑数" : ""}。</p>
    {result.outputs.length > 0 && <ul>{result.outputs.map(output => {
      const trace = openingPreviewTraces.find(item => item.outputId === output.output_id);
      const previewStatus = trace?.finalDurationMs == null ? "无开场预告" : `开场预告 ${formatSeconds(trace.finalDurationMs)} 秒${trace.finalWithinBounds ? "（符合范围）" : "（建议检查）"}`;
      return <li key={output.output_id}>{output.title} · {(output.duration_ms / 1000).toFixed(1)} 秒{bounds ? ` · ${previewStatus}` : ""}</li>;
    })}</ul>}
    {bounds && <section className="opening-preview-section">
      <h3>开场预告处理过程</h3>
      <p>目标 {formatSeconds(result.brief.hook_ms as number)} 秒，允许 {formatSeconds(bounds[0])}–{formatSeconds(bounds[1])} 秒；最终 {generatedOpeningPreviews} 条已采用，{missingOpeningPreviews} 条未采用。以下过程由现有生成记录与最终保存结果整理，不会再次调用 AI。</p>
      <div className="opening-preview-traces">{openingPreviewTraces.map(trace => <details className="opening-preview-trace" key={trace.outputId}>
        <summary>{trace.title} · {trace.finalDurationMs == null ? "最终未添加" : `最终 ${formatSeconds(trace.finalDurationMs)} 秒${trace.finalWithinBounds ? "，符合范围" : "，建议检查"}`}</summary>
        <ol>{trace.steps.map((step, index) => <li key={`${trace.outputId}-${index}`}>{step}</li>)}</ol>
      </details>)}</div>
      {openingPreviewNotes.length > 0 && <><h4>生成阶段补充记录</h4><ul>{openingPreviewNotes.map(note => <li key={note}>{note}</li>)}</ul></>}
      {missingOpeningPreviews > 0 && <p>{missingOpeningPreviews} 条未找到同时满足时长与完整原话要求的内容；可在编辑页试听并手动调整。</p>}
    </section>}
    {boundaryWarnings.length > 0 && <section><h3>需要检查</h3><ul>{boundaryWarnings.map(note => <li key={note}>{note}</li>)}</ul></section>}
    {explanations.length > 0 && <section><h3>选材说明</h3><ul>{explanations.map(note => <li key={note}>{note}</li>)}</ul></section>}
  </details>;
}
