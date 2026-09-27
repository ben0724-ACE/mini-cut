import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HighlightPanel } from "./HighlightPanel";
import { startHighlights, getHighlights, getGenerationDraft, saveGenerationDraft, getGenerationHistory, listGenerationPresets } from "./api";
vi.mock("./api", async original => ({...await original<typeof import("./api")>(), getGenerationDraft: vi.fn().mockResolvedValue({source:"default",draft:null}), saveGenerationDraft: vi.fn().mockImplementation(async (_project,_asset,draft)=>({source:"asset",draft})), getGenerationHistory: vi.fn().mockResolvedValue([]), listGenerationPresets: vi.fn().mockResolvedValue([]), startHighlights: vi.fn().mockResolvedValue({task_id:"new",status:"pending",result:null,error:null}), getHighlights: vi.fn().mockResolvedValue({selected_output_ids: []}), saveHighlightSelection: vi.fn().mockResolvedValue({selected_output_ids:["video-1"]})}));

beforeEach(()=>{localStorage.clear();vi.mocked(getGenerationDraft).mockResolvedValue({source:"default",draft:null});vi.mocked(saveGenerationDraft).mockImplementation(async (_project,_asset,draft)=>({source:"asset",draft}));vi.mocked(getGenerationHistory).mockResolvedValue([]);vi.mocked(listGenerationPresets).mockResolvedValue([]);});

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
  expect(screen.getByText(/已生成 1 \/ 3 条候选/)).toBeInTheDocument();
  expect(screen.getByText(/源素材：播客.mov/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", {name: "选择有趣观点"}));
  await waitFor(() => expect(screen.getByRole("checkbox", {name: "选择有趣观点"})).toBeChecked());
  await userEvent.click(screen.getByRole("checkbox", {name: "只看已选作品"}));
  expect(screen.getByRole("button",{name:"有趣观点"})).toBeInTheDocument();
});

it("点击候选直接进入编辑，切换作品不回到生成", async () => {
  const result = {collection_id:"two",asset_id:"asset",brief:{preset:"podcast_highlights",count:2,min_ms:60000,max_ms:90000,hook_ms:null,instructions:"",max_source_overlap:0.3},notes:[],selected_output_ids:[],outputs:[{output_id:"video-1",title:"第一条",reason:"独立观点",duration_ms:61000,clips:[],revision:1},{output_id:"video-2",title:"第二条",reason:"不同观点",duration_ms:62000,clips:[],revision:1}]};
  vi.mocked(getHighlights).mockResolvedValue(result);
  const view=render(<HighlightPanel project="demo" asset={{asset_id:"asset",name:"test.mov",duration_ms:100000,has_transcript:true,has_plan:false}} recover={vi.fn().mockResolvedValue({task_id:"job",status:"succeeded",error:null,result})} transcription={<div>转录设置</div>} />);
  expect(view.container.querySelector(".workbench-sidebar")).not.toHaveTextContent("转录设置");
  expect(screen.getByRole("tabpanel",{name:"生成",hidden:true})).toHaveTextContent("转录设置");
  const candidates=screen.getByRole("region",{name:"候选作品列表"});
  candidates.scrollTop=120;
  fireEvent.scroll(candidates);
  await userEvent.click(await screen.findByRole("button",{name:"第一条"}));
  expect(screen.getByRole("tab",{name:"编辑"})).toHaveAttribute("aria-selected","true");
  expect(screen.getByRole("region",{name:"候选作品列表"}).scrollTop).toBe(120);
  await userEvent.click(screen.getByRole("tab",{name:"导出"}));
  await userEvent.click(screen.getByRole("button",{name:"第二条"}));
  await waitFor(()=>expect(screen.getByRole("tab",{name:"编辑"})).toHaveAttribute("aria-selected","true"));
  expect(screen.getByRole("region",{name:"候选作品列表"}).scrollTop).toBe(120);
});

it("从结果页返回时恢复导出面板",async()=>{
  const result={collection_id:"saved",asset_id:"asset",brief:{preset:"podcast_highlights",count:1,min_ms:60000,max_ms:90000,hook_ms:null,instructions:"",max_source_overlap:0.3},notes:[],selected_output_ids:[],outputs:[{output_id:"video-1",title:"已导出作品",reason:"完整讨论",duration_ms:61000,clips:[],revision:1}]};
  vi.mocked(getHighlights).mockResolvedValue(result);
  window.history.replaceState({},"","/?project=demo&panel=export");
  try {
    render(<HighlightPanel project="demo" asset={{asset_id:"asset",name:"test.mov",duration_ms:100000,has_transcript:true,has_plan:false}} recover={vi.fn().mockResolvedValue({task_id:"job",status:"succeeded",error:null,result})} />);
    await waitFor(()=>expect(screen.getByRole("tab",{name:"导出"})).toHaveAttribute("aria-selected","true"));
  } finally {
    window.history.replaceState({},"","/");
  }
});

it("生成完成、切换作品造成表单重挂载后仍保留项目草稿", async()=>{
  const {defaultGenerationDraft} = await import("./generationDraft");
  const saved = {...defaultGenerationDraft(),instructions:"保存的要求",hook_seconds:12.5,translation_language:"en" as const,prompts:{...defaultGenerationDraft().prompts,opinion_first:"未使用的预设草稿"}};
  vi.mocked(getGenerationDraft).mockResolvedValue({source:"asset",draft:saved});
  const result={collection_id:"generated",asset_id:"asset",brief:{preset:"podcast_highlights",count:3,min_ms:60000,max_ms:90000,hook_ms:null,instructions:"保存的要求",max_source_overlap:0.3},notes:[],outputs:[{output_id:"first",title:"生成后的作品",reason:"完整",duration_ms:60000,clips:[],revision:1}]};
  vi.mocked(startHighlights).mockResolvedValueOnce({task_id:"generated",status:"succeeded",result,error:null});
  vi.mocked(getHighlights).mockResolvedValue(result);
  render(<HighlightPanel project="remount" asset={{asset_id:"asset",name:"test.mov",duration_ms:100000,has_transcript:true,has_plan:false}} recover={vi.fn().mockResolvedValue(null)} />);
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成候选"})).toBeEnabled());
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("保存的要求");
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  await screen.findByRole("button",{name:"生成后的作品"});
  await userEvent.click(screen.getByRole("tab",{name:"生成"}));
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("保存的要求");
  await userEvent.selectOptions(screen.getByLabelText("预设"),"opinion_first");
  expect(screen.getByLabelText("预设提示词")).toHaveValue("未使用的预设草稿");
  await userEvent.click(screen.getByLabelText("原话开场预告"));
  expect(screen.getByLabelText("开场预告目标秒数")).toHaveValue(12.5);
  await userEvent.click(screen.getByLabelText("翻译字幕"));
  expect(screen.getByLabelText("翻译为")).toHaveValue("en");
});

it("恢复草稿失败时禁止用默认值覆盖记录，重试后才能生成", async()=>{
  vi.mocked(getGenerationDraft).mockRejectedValueOnce(new Error("读取失败"));
  render(<HighlightPanel project="read-failure" asset={{asset_id:"asset",name:"test.mov",duration_ms:100000,has_transcript:true,has_plan:false}} recover={vi.fn().mockResolvedValue(null)} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("无法恢复生成草稿");
  expect(screen.getByRole("button",{name:"生成候选"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"重试恢复草稿"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成候选"})).toBeEnabled());
});
