import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PlanDetail } from "./api";
import { PlanReview } from "./PlanReview";

const plan: PlanDetail = {
  asset_id: "asset-1",
  revision: 2,
  available_revisions: [1, 2],
  summary: "保留核心观点",
  target_duration_ms: 10_000,
  intensity: "balanced",
  style: "concise",
  segments: [
    { segment_id: "s1", text: "核心观点", start_ms: 0, end_ms: 1200, action: "keep", reason: "core_content", confidence: 0.9, explanation: "承载主要信息" },
    { segment_id: "s2", text: "重复内容", start_ms: 1200, end_ms: 2400, action: "delete", reason: "repetition", confidence: 0.8, explanation: "与前文重复" },
  ],
};

describe("PlanReview", () => {
  it("shows keep/delete decisions, reasons and counts", () => {
    render(<PlanReview initialPlan={plan} saveDecision={vi.fn()} mediaUrl="/media" />);
    expect(screen.getByText("核心观点")).toBeInTheDocument();
    expect(screen.getByText("重复内容")).toBeInTheDocument();
    expect(screen.getByText(/承载主要信息/)).toBeInTheDocument();
    expect(screen.getByText(/与前文重复/)).toBeInTheDocument();
    expect(screen.getByText("00:01.2")).toBeInTheDocument();
    expect(screen.getByText("暂无变化")).toBeInTheDocument();
    expect(screen.getByText("保留", { selector: "dt" }).nextSibling).toHaveTextContent("1");
    expect(screen.getByText("删除", { selector: "dt" }).nextSibling).toHaveTextContent("1");
  });

  it("persists a decision and can undo it through the API callback", async () => {
    const user = userEvent.setup();
    const saveDecision = vi
      .fn()
      .mockResolvedValueOnce({
        ...plan,
        revision: 3,
        segments: plan.segments.map((segment) =>
          segment.segment_id === "s2" ? { ...segment, action: "keep" } : segment,
        ),
      })
      .mockResolvedValueOnce(plan);
    render(<PlanReview initialPlan={plan} saveDecision={saveDecision} mediaUrl="/media" />);

    await user.click(screen.getByRole("button", { name: "恢复此段" }));
    expect(saveDecision).toHaveBeenLastCalledWith("s2", "keep");
    expect(screen.getByText("Revision 3")).toBeInTheDocument();
    expect(screen.getByText("保留", { selector: "dt" }).nextSibling).toHaveTextContent("2");
    expect(screen.getByText("00:02.4")).toBeInTheDocument();
    expect(screen.getByText("+00:01.2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "撤销上次修改" }));
    expect(saveDecision).toHaveBeenLastCalledWith("s2", "delete");
    expect(screen.getByText("Revision 2")).toBeInTheDocument();
  });

  it("seeks from text and supports keyboard editing and playback", async () => {
    const user = userEvent.setup();
    const saveDecision = vi.fn().mockResolvedValue({
      ...plan,
      revision: 3,
      segments: plan.segments.map((segment) =>
        segment.segment_id === "s1"
          ? { ...segment, action: "delete" as const }
          : segment,
      ),
    });
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    render(
      <PlanReview initialPlan={plan} saveDecision={saveDecision} mediaUrl="/media" />,
    );
    const video = screen.getByText("浏览器无法播放这个视频。") as HTMLVideoElement;

    await user.click(screen.getByText("重复内容"));
    expect(video.currentTime).toBe(1.2);

    screen.getByLabelText("保留片段：核心观点").focus();
    await user.keyboard("d");
    expect(saveDecision).toHaveBeenCalledWith("s1", "delete");

    screen.getByLabelText("删除片段：重复内容").focus();
    await user.keyboard(" ");
    expect(video.currentTime).toBe(1.2);
    expect(play).toHaveBeenCalledOnce();
  });
});
