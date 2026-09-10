import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
    render(<PlanReview plan={plan} />);
    expect(screen.getByText("核心观点")).toBeInTheDocument();
    expect(screen.getByText("重复内容")).toBeInTheDocument();
    expect(screen.getByText(/承载主要信息/)).toBeInTheDocument();
    expect(screen.getByText(/与前文重复/)).toBeInTheDocument();
    expect(screen.getByText("保留", { selector: "dt" }).nextSibling).toHaveTextContent("1");
    expect(screen.getByText("删除", { selector: "dt" }).nextSibling).toHaveTextContent("1");
  });
});
