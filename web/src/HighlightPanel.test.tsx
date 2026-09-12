import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HighlightPanel } from "./HighlightPanel";

it("恢复数量不足结果并显示候选标题理由及源素材", async () => {
  render(<HighlightPanel project="demo" asset={{asset_id: "asset", name: "播客.mov", duration_ms: 100000, has_transcript: true, has_plan: false}} recover={vi.fn().mockResolvedValue({task_id: "job", status: "succeeded", error: null, result: {collection_id: "one", asset_id: "asset", notes: ["数量不足：实际1条"], outputs: [{output_id: "video-1", title: "有趣观点", reason: "完整讨论", duration_ms: 61000, clips: [], revision: 1}]}})} />);
  expect(await screen.findByText("有趣观点")).toBeInTheDocument();
  expect(screen.getByText("完整讨论")).toBeInTheDocument();
  expect(screen.getByText("数量不足：实际1条")).toBeInTheDocument();
  expect(screen.getByText(/源素材：播客.mov/)).toBeInTheDocument();
});
