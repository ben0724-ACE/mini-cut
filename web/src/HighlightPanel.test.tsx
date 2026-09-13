import { expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HighlightPanel } from "./HighlightPanel";
import { startHighlights, getHighlights } from "./api";
vi.mock("./api", async original => ({...await original<typeof import("./api")>(), startHighlights: vi.fn().mockResolvedValue({task_id:"new",status:"pending",result:null,error:null}), getHighlights: vi.fn().mockResolvedValue({selected_output_ids: []}), saveHighlightSelection: vi.fn().mockResolvedValue({selected_output_ids:["video-1"]})}));

it("连续点击只提交一个生成任务", async () => {
  vi.mocked(startHighlights).mockClear();
  render(<HighlightPanel project="demo" asset={{asset_id:"asset",name:"test.mov",duration_ms:100000,has_transcript:true,has_plan:false}} recover={vi.fn().mockResolvedValue(null)} />);
  await waitFor(() => expect(screen.getByRole("button",{name:"生成候选"})).toBeEnabled());
  await userEvent.dblClick(screen.getByRole("button",{name:"生成候选"}));
  expect(startHighlights).toHaveBeenCalledOnce();
});
it("恢复失败生成时保留真实错误，可重新生成", async () => {
  render(<HighlightPanel project="demo" asset={{asset_id:"asset",name:"test.mov",duration_ms:100000,has_transcript:true,has_plan:false}} recover={vi.fn().mockResolvedValue({task_id:"failed",status:"failed",result:null,error:"服务额度不足"})} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("服务额度不足");
  expect(screen.getByRole("button",{name:"生成候选"})).toBeEnabled();
});

it("恢复数量不足结果并显示候选标题理由及源素材", async () => {
  vi.mocked(getHighlights).mockResolvedValue({collection_id:"one",asset_id:"asset",brief:{preset:"podcast_highlights",count:3,min_ms:60000,max_ms:90000,hook_ms:null,instructions:"",max_source_overlap:0.3},notes:["数量不足：实际1条"],selected_output_ids:[],outputs:[{output_id:"video-1",title:"有趣观点",reason:"完整讨论",duration_ms:61000,clips:[],revision:1}]});
  render(<HighlightPanel project="demo" asset={{asset_id: "asset", name: "播客.mov", duration_ms: 100000, has_transcript: true, has_plan: false}} recover={vi.fn().mockResolvedValue({task_id: "job", status: "succeeded", error: null, result: {collection_id: "one", asset_id: "asset", notes: ["数量不足：实际1条"], outputs: [{output_id: "video-1", title: "有趣观点", reason: "完整讨论", duration_ms: 61000, clips: [], revision: 1}]}})} />);
  expect(await screen.findByRole("button",{name:"有趣观点"})).toBeInTheDocument();
  expect(screen.getByText("完整讨论")).toBeInTheDocument();
  expect(screen.getByText("数量不足：实际1条")).toBeInTheDocument();
  expect(screen.getByText(/源素材：播客.mov/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", {name: "选择有趣观点"}));
  await waitFor(() => expect(screen.getByRole("checkbox", {name: "选择有趣观点"})).toBeChecked());
  await userEvent.click(screen.getByRole("checkbox", {name: "只看已选作品"}));
  expect(screen.getByRole("button",{name:"有趣观点"})).toBeInTheDocument();
});
