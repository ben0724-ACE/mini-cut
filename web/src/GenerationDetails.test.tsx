import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { GenerationDetails } from "./GenerationDetails";
import type { HighlightResult } from "./api";

it("以最终作品为准汇总旧结果，去掉重复和过时的模型估算", () => {
  const result: HighlightResult = {
    collection_id: "one", asset_id: "asset", brief: {preset: "podcast_highlights", count: 3, min_ms: 1000, max_ms: 120000, hook_ms: 10000, instructions: "", max_source_overlap: 0.3},
    outputs: [{output_id: "one", title: "AI 安全", reason: "完整讨论", revision: 1, duration_ms: 48400, clips: []}, {output_id: "two", title: "AI 火箭", reason: "完整讨论", revision: 1, duration_ms: 11200, clips: []}],
    notes: ["仅返回2条候选，未凑足brief.count=3：缺少第三个独立话题。", "两个候选均未找到长度落在7000–13000 ms内的钩子：提问太短，故hook_segment_ids均留空。", "Hugging Face候选为连续正文，约54秒。", "AI 安全：未找到独立原话钩子，保留正文。", "数量不足：要求 3 条，实际 2 条；未凑数。", "AI 安全：建议检查开头／结尾，语义边界未确定。", "AI 安全：未确认独立短句，不添加钩子。", "句界复核后保留 2 条，少于目标 3 条；未凑数。"],
  };
  const view = render(<GenerationDetails assetName="source.mp4" result={result} />);
  expect(screen.getByText(/已生成 2 \/ 3 条候选/)).toBeInTheDocument();
  expect(screen.getByText(/AI 安全 · 48.4 秒 · 无开场钩子/)).toBeInTheDocument();
  expect(screen.getByText(/候选不足原因：缺少第三个独立话题/)).toBeInTheDocument();
  expect(screen.getByText(/钩子原因：提问太短/)).toBeInTheDocument();
  expect(view.container).not.toHaveTextContent("hook_segment_ids");
  expect(screen.getByText(/建议检查开头／结尾/)).toBeInTheDocument();
  expect(view.container).not.toHaveTextContent("约54秒");
  expect(view.container).not.toHaveTextContent("句界复核后保留");
  expect(view.container).not.toHaveTextContent("未确认独立短句");
});
