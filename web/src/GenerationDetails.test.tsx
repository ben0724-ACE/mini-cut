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
  expect(screen.getByText(/AI 安全 · 48.4 秒 · 无开场预告/)).toBeInTheDocument();
  expect(screen.getByText(/候选不足原因：缺少第三个独立话题/)).toBeInTheDocument();
  expect(screen.getByText(/开场预告：提问太短/)).toBeInTheDocument();
  expect(view.container).not.toHaveTextContent("hook_segment_ids");
  expect(screen.getByText(/建议检查开头／结尾/)).toBeInTheDocument();
  expect(view.container).not.toHaveTextContent("约54秒");
  expect(view.container).not.toHaveTextContent("句界复核后保留");
  expect(screen.getByText(/词级复核：仍未确认符合要求的独立完整原话/)).toBeInTheDocument();
});

it("按作品展示初选淘汰、词级复核和最终开场预告结果", () => {
  const result: HighlightResult = {
    collection_id: "three", asset_id: "asset",
    brief: {preset: "podcast_highlights", count: 5, min_ms: 30000, max_ms: 200000, hook_ms: 10000, instructions: "AI", max_source_overlap: 0.3},
    outputs: [
      {output_id: "one", title: "开放模型", reason: "完整", revision: 1, duration_ms: 64780, clips: []},
      {output_id: "two", title: "AI 监管", reason: "完整", revision: 1, duration_ms: 51000, clips: [
        {instance_id: "h1", segment_id: "s1", role: "hook", text: "A", start_ms: 2935460, end_ms: 2937200},
        {instance_id: "h2", segment_id: "s2", role: "hook", text: "B", start_ms: 2937200, end_ms: 2944200},
      ]},
      {output_id: "three", title: "AI 基础设施", reason: "完整", revision: 1, duration_ms: 108280, clips: [
        {instance_id: "h3", segment_id: "s3", role: "hook", text: "C", start_ms: 1892240, end_ms: 1896420},
        {instance_id: "h4", segment_id: "s4", role: "hook", text: "D", start_ms: 1896420, end_ms: 1902840},
      ]},
    ],
    notes: [
      "第三个候选的钩子边界跨相邻句子，引用约十秒完整原话，满足时长范围。",
      "开放模型：初选钩子未通过：实测 5.4 秒，不在允许的 7–13 秒范围内。省略初选钩子，连续模式继续词级复核。",
      "开放模型：未找到独立原话钩子，保留正文。",
      "开放模型：未确认独立短句，不添加钩子。",
      "AI 监管：初选钩子未通过：实测 6.16 秒，不在允许的 7–13 秒范围内。省略初选钩子，连续模式继续词级复核。",
      "AI 监管：未找到独立原话钩子，保留正文。",
      "AI 基础设施：词级复核未提供有效替代钩子，保留初选已校验的完整原话；请试听确认。",
    ],
  };
  const view = render(<GenerationDetails assetName="source.mp4" result={result} />);

  expect(screen.getByText(/AI 监管 · 51.0 秒 · 开场预告 8.74 秒（符合范围）/)).toBeInTheDocument();
  expect(screen.getByText(/AI 基础设施 · 108.3 秒 · 开场预告 10.6 秒（符合范围）/)).toBeInTheDocument();
  expect(screen.getByText(/最终 2 条已采用，1 条未采用/)).toBeInTheDocument();
  expect(screen.getByText("AI 初选：选出 6.16 秒的开场预告。")).toBeInTheDocument();
  expect(screen.getAllByText(/本地校验：未通过，不在 7–13 秒允许范围内/)).toHaveLength(2);
  expect(screen.getByText("词级复核：重新选出 8.74 秒的完整原话。")).toBeInTheDocument();
  expect(screen.getByText(/最终结果：采用 8.74 秒开场预告，符合 7–13 秒范围/)).toBeInTheDocument();
  expect(screen.getByText(/词级复核：没有提供更合适的有效替代，保留已通过校验的初选原话/)).toBeInTheDocument();
  expect(screen.getByText(/第三个候选的开场预告边界跨相邻句子/)).toBeInTheDocument();
  expect(view.container).not.toHaveTextContent("AI 监管：未找到独立原话钩子，保留正文");
});
