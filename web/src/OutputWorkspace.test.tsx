import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OutputWorkspace } from "./OutputWorkspace";
vi.mock("./api", async original => ({...await original<typeof import("./api")>(), getHighlights: vi.fn().mockResolvedValue({asset_id:"source",outputs:[{output_id:"video-1",title:"作品A",reason:"理由A",revision:1,clips:[]},{output_id:"video-2",title:"作品B",reason:"理由B",revision:2,clips:[]}]})}));
it("独立作品入口只显示指定计划，不串其他作品", async () => {
  const view = render(<OutputWorkspace project="demo" collection="one" output="video-1" />);
  expect(await screen.findByRole("heading",{name:"作品A"})).toBeInTheDocument();
  view.rerender(<OutputWorkspace key="video-2" project="demo" collection="one" output="video-2" />);
  expect(await screen.findByRole("heading",{name:"作品B"})).toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:"作品A"})).not.toBeInTheDocument();
});

it("范围草稿撤销与批量保存不调用渲染，显式生成才启动",async()=>{
  const api=await import("./api");
  const preview=vi.spyOn(api,"startOutputPreview").mockResolvedValue({task_id:"p",status:"pending",result:null,error:null});
  vi.spyOn(api,"recoverOutputPreview").mockResolvedValue(null);
  const clip={instance_id:"i",segment_id:"s",role:"body" as const,text:"A",start_ms:2000,end_ms:8000};
  const data={asset_id:"a",collection_id:"c",source_duration_ms:20000,notes:[],brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:null,instructions:"",max_source_overlap:1},outputs:[{output_id:"o",title:"草稿",reason:"完整",revision:1,duration_ms:6000,clips:[clip]}]};
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const save=vi.spyOn(api,"saveOutputRanges").mockResolvedValue({...data,outputs:[{...data.outputs[0],revision:2,clips:[{...clip,start_ms:2500}]}]});
  render(<OutputWorkspace project="p" collection="c" output="o" />);
  await screen.findByLabelText("快速预览 · 草稿");
  const {fireEvent}=await import("@testing-library/react");
  fireEvent.click(screen.getByLabelText("编辑字幕 i"));
  fireEvent.click(screen.getByText("开始 ＋"));expect(screen.getByLabelText("开始 i")).toHaveValue(2.5);
  fireEvent.click(screen.getByText("撤销"));expect(screen.getByLabelText("开始 i")).toHaveValue(2);
  fireEvent.click(screen.getByText("重做"));expect(screen.getByLabelText("开始 i")).toHaveValue(2.5);
  expect(screen.getByText("生成成片预览")).toBeDisabled();
  fireEvent.click(screen.getByText("保存修改"));
  const {waitFor}=await import("@testing-library/react");
  await waitFor(()=>expect(save).toHaveBeenCalledWith("p","c","o",1,[{instance_id:"i",source_start_ms:2500,source_end_ms:8000}]));
  await waitFor(()=>expect(screen.getByText("生成成片预览")).toBeEnabled());
  expect(preview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("生成成片预览"));await waitFor(()=>expect(preview).toHaveBeenCalledOnce());
});

it("逐句编辑提示只在作品级说明中出现一次", async () => {
  const api = await import("./api");
  const clips = [
    {instance_id:"first",segment_id:"a",role:"body" as const,text:"第一句",start_ms:0,end_ms:2000},
    {instance_id:"second",segment_id:"b",role:"body" as const,text:"第二句",start_ms:2000,end_ms:4000},
  ];
  vi.mocked(api.getHighlights).mockResolvedValue({
    asset_id:"a",collection_id:"c",source_duration_ms:4000,notes:[],
    brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:null,instructions:"",max_source_overlap:1},
    outputs:[{output_id:"o",title:"两句测试",reason:"完整",revision:1,duration_ms:4000,clips}],
  });
  const {container}=render(<OutputWorkspace project="p" collection="c" output="o" />);
  await screen.findByLabelText("编辑字幕 second");
  expect(screen.getAllByText("编辑说明（范围、字幕与分句）")).toHaveLength(1);
  expect(screen.getAllByText(/手动分句时，在字幕中/)).toHaveLength(1);
  expect(container.querySelectorAll(".subtitle-card .helper-text")).toHaveLength(0);
  expect(screen.getAllByLabelText("全局字幕显示")).toHaveLength(1);
  expect(screen.queryByLabelText("字幕显示 first")).not.toBeInTheDocument();
});

it("编辑页只提示待检查的边界，不重复初选与复核的钩子说明", async () => {
  const api = await import("./api");
  vi.mocked(api.getHighlights).mockResolvedValue({
    asset_id:"a",collection_id:"c",source_duration_ms:4000,
    notes:["作品A：未找到独立原话钩子，保留正文。","作品A：建议检查开头／结尾，语义边界未确定。","作品A：未确认独立短句，不添加钩子。"],
    brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:5000,instructions:"",max_source_overlap:1},
    outputs:[{output_id:"video-1",title:"作品A",reason:"理由",revision:2,duration_ms:2000,clips:[]}],
  });
  render(<OutputWorkspace project="demo" collection="one" output="video-1" />);
  expect(await screen.findByText("初始生成时的边界提示")).toBeInTheDocument();
  expect(screen.getByText("建议检查开头／结尾，语义边界未确定。")).toBeInTheDocument();
  expect(screen.queryByText(/未找到独立原话钩子/)).not.toBeInTheDocument();
  expect(screen.queryByText(/未确认独立短句/)).not.toBeInTheDocument();
});

it("切换三个编辑区域保留逐句字幕与范围草稿", async () => {
  const api=await import("./api");
  const clip={instance_id:"sentence",segment_id:"s",role:"body" as const,text:"Original",translation_text:"译文",translation_language:"zh" as const,start_ms:2000,end_ms:5000};
  vi.mocked(api.getHighlights).mockResolvedValue({asset_id:"a",collection_id:"c",source_duration_ms:10000,notes:[],brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:null,instructions:"",max_source_overlap:1},outputs:[{output_id:"o",title:"切换测试",reason:"完整",revision:1,duration_ms:3000,clips:[clip]}]});
  render(<OutputWorkspace project="p" collection="c" output="o" />);
  await screen.findByLabelText("编辑字幕 sentence");
  fireEvent.click(screen.getByLabelText("编辑字幕 sentence"));
  fireEvent.change(screen.getByLabelText("字幕 sentence"),{target:{value:"Revised original"}});
  fireEvent.change(screen.getByLabelText("译文 sentence"),{target:{value:"修改后的译文"}});
  fireEvent.click(screen.getByText("开始 ＋"));
  expect(screen.getByLabelText("开始 sentence")).toHaveValue(2.5);
  fireEvent.click(screen.getByRole("tab",{name:/字幕设置/}));
  expect(screen.getByRole("tabpanel",{name:"字幕设置"})).toBeVisible();
  expect(document.getElementById(screen.getByRole("tab",{name:/逐句编辑/}).getAttribute("aria-controls")!)).not.toBeVisible();
  fireEvent.click(screen.getByRole("tab",{name:/开场预告/}));
  expect(screen.getByRole("tabpanel",{name:/开场预告/})).toBeVisible();
  fireEvent.click(screen.getByRole("tab",{name:/逐句编辑/}));
  expect(screen.getByLabelText("字幕 sentence")).toHaveValue("Revised original");
  expect(screen.getByLabelText("译文 sentence")).toHaveValue("修改后的译文");
  expect(screen.getByLabelText("开始 sentence")).toHaveValue(2.5);
  expect(screen.getByRole("tab",{name:/逐句编辑/})).toHaveTextContent("未保存");
});

it("开场预告区域可从正文选择原话并复制为预告", async () => {
  const api=await import("./api");
  const clips=[
    {instance_id:"first",segment_id:"a",role:"body" as const,text:"第一句",start_ms:0,end_ms:2000},
    {instance_id:"second",segment_id:"b",role:"body" as const,text:"第二句",start_ms:2000,end_ms:4000},
  ];
  const data={asset_id:"a",collection_id:"c",source_duration_ms:4000,notes:[],brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:2000,instructions:"",max_source_overlap:1},outputs:[{output_id:"o",title:"预告测试",reason:"完整",revision:1,duration_ms:4000,clips}]};
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const reorder=vi.spyOn(api,"reorderOutput").mockResolvedValue({...data,outputs:[{...data.outputs[0],revision:2,clips:[{...clips[1],instance_id:"second-hook-v2",role:"hook" as const},...clips]}]});
  render(<OutputWorkspace project="p" collection="c" output="o" />);
  await screen.findByLabelText("编辑字幕 second");
  fireEvent.click(screen.getByRole("tab",{name:"开场预告"}));
  fireEvent.change(screen.getByLabelText("选择预告原话"),{target:{value:"second"}});
  fireEvent.click(screen.getByRole("button",{name:"复制为开场预告"}));
  await waitFor(()=>expect(reorder).toHaveBeenCalledWith("p","c","o",["second","first"],{second:"hook"}));
  expect(await screen.findByLabelText("编辑字幕 second-hook-v2")).toBeInTheDocument();
});
