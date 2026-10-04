import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { OutputWorkspace } from "./OutputWorkspace";
vi.mock("./api", async original => ({...await original<typeof import("./api")>(), listSubtitleFonts:vi.fn().mockResolvedValue([]), getHighlights: vi.fn().mockResolvedValue({asset_id:"source",outputs:[{output_id:"video-1",title:"作品A",reason:"理由A",revision:1,clips:[]},{output_id:"video-2",title:"作品B",reason:"理由B",revision:2,clips:[]}]})}));
vi.mock("./exportSettingsApi",async original=>{
  const actual=await original<typeof import("./exportSettingsApi")>();
  const drafts=new Map<string,import("./exportSettingsApi").ExportDraft>();
  return {...actual,
    getExportDraft:vi.fn().mockImplementation(async(route:string)=>({source:drafts.has(route)?"saved":"default",draft:drafts.get(route)??actual.defaultExportDraft()})),
    saveExportDraft:vi.fn().mockImplementation(async(route:string,draft:import("./exportSettingsApi").ExportDraft)=>{drafts.set(route,draft);return {source:"saved",draft};}),
    listExportPresets:vi.fn().mockResolvedValue([]),
  };
});

function subtitleFixture() {
  const clips = [
    {instance_id:"first",segment_id:"a",role:"body" as const,text:"First",translation_text:"第一句",translation_language:"zh" as const,start_ms:0,end_ms:2000},
    {instance_id:"second",segment_id:"b",role:"body" as const,text:"Second",translation_text:"第二句",translation_language:"zh" as const,start_ms:2000,end_ms:4000},
  ];
  return {asset_id:"a",collection_id:"c",source_duration_ms:10000,notes:[],brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:null,instructions:"",max_source_overlap:1},outputs:[{output_id:"o",title:"字幕草稿",reason:"完整",revision:1,duration_ms:4000,clips}]};
}

async function openSubtitleDrafts() {
  await screen.findByLabelText("编辑字幕 second");
  fireEvent.click(screen.getByRole("tab",{name:"逐句编辑"}));
  for (const id of ["first", "second"]) {
    fireEvent.click(screen.getByLabelText(`编辑字幕 ${id}`));
    fireEvent.change(screen.getByLabelText(`字幕 ${id}`),{target:{value:`Unsaved ${id} draft`}});
    fireEvent.change(screen.getByLabelText(`译文 ${id}`),{target:{value:`未保存的${id}译文`}});
  }
}

function subtitleCard(id:string) {
  return within(screen.getByLabelText(`编辑字幕 ${id}`).closest("li")!);
}

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
  fireEvent.click(screen.getByRole("tab",{name:"逐句编辑"}));
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
  fireEvent.click(screen.getByRole("tab",{name:"逐句编辑"}));
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
  fireEvent.click(screen.getByRole("tab",{name:"逐句编辑"}));
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
  fireEvent.click(screen.getByRole("tab",{name:"逐句编辑"}));
  fireEvent.click(screen.getByRole("tab",{name:"开场预告"}));
  fireEvent.change(screen.getByLabelText("选择预告原话"),{target:{value:"second"}});
  fireEvent.click(screen.getByRole("button",{name:"复制为开场预告"}));
  await waitFor(()=>expect(reorder).toHaveBeenCalledWith("p","c","o",["second","first"],{second:"hook"}));
  expect(await screen.findByLabelText("编辑字幕 second-hook-v2")).toBeInTheDocument();
});
it("编辑阶段设置画幅同步到导出，修改后保留旧预览并显式更新；字幕保存后仍停留成片模式",async()=>{
  const {within}=await import("@testing-library/react");const api=await import("./api");const user=(await import("@testing-library/user-event")).default.setup();
  const data={asset_id:"a",collection_id:"c",source_duration_ms:2000,notes:[],brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:null,instructions:"",max_source_overlap:1},outputs:[{output_id:"o",title:"同步测试",reason:"",revision:1,duration_ms:2000,clips:[]}]};
  vi.mocked(api.getHighlights).mockResolvedValue(data);vi.spyOn(api,"recoverOutputPreview").mockResolvedValue(null);const preview=vi.spyOn(api,"startOutputPreview").mockImplementation(async(_p,_c,_o,revision,_key,options)=>({task_id:"preview",status:"succeeded",error:null,result:{revision,output_id:"o",media_url:`/${options?.aspect_ratio}-${revision}.mp4`,subtitle_url:"/sub.srt",duration_ms:2000}}));
  const save=vi.spyOn(api,"saveOutputSubtitleSettings").mockResolvedValue({...data,outputs:[{...data.outputs[0],revision:2,subtitle_style:{...api.defaultSubtitleStyle(),source_size:72}}]});
  render(<OutputWorkspace project="workspace-sync" collection="c" output="o"/>);await screen.findByLabelText("快速预览 · 同步测试");const frame=within(screen.getByRole("tabpanel",{name:"画面设置"}));
  await waitFor(()=>expect(frame.getByLabelText("作品比例")).toBeEnabled());await user.selectOptions(frame.getByLabelText("作品比例"),"9:16");await user.click(screen.getByRole("tab",{name:"字幕设置"}));await user.selectOptions(screen.getByLabelText("字幕方式"),"burned");
  const exporting=within(screen.getByRole("region",{name:"单作品导出",hidden:true}));expect(exporting.getByText("9:16 · 1080×1920 · 烧录字幕")).toBeInTheDocument();expect(exporting.queryByRole("combobox")).not.toBeInTheDocument();expect(preview).not.toHaveBeenCalled();await user.click(screen.getByRole("button",{name:"生成成片预览"}));expect(await screen.findByLabelText("成片预览 · 同步测试")).toHaveAttribute("src","/9:16-1.mp4");
  await user.click(screen.getByRole("tab",{name:"画面设置"}));await user.selectOptions(frame.getByLabelText("作品比例"),"1:1");expect(screen.getByLabelText("成片预览 · 同步测试")).toHaveAttribute("src","/9:16-1.mp4");expect(preview).toHaveBeenCalledTimes(1);expect(screen.getByText(/设置或作品版本已变化/)).toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"更新成片预览"}));expect(await screen.findByLabelText("成片预览 · 同步测试")).toHaveAttribute("src","/1:1-1.mp4");
  await user.click(screen.getByRole("tab",{name:"字幕设置"}));fireEvent.change(screen.getByLabelText("原文字号"),{target:{value:"72"}});expect(screen.getByRole("button",{name:"更新成片预览"})).toBeDisabled();await user.click(screen.getByRole("button",{name:"保存字幕设置"}));await waitFor(()=>expect(save).toHaveBeenCalled());await waitFor(()=>expect(screen.getByRole("button",{name:"更新成片预览"})).toBeEnabled());
  expect(screen.getByLabelText("成片预览 · 同步测试")).toHaveAttribute("src","/1:1-1.mp4");expect(screen.queryByLabelText("快速预览 · 同步测试")).not.toBeInTheDocument();expect(preview).toHaveBeenCalledTimes(2);await user.click(screen.getByRole("button",{name:"更新成片预览"}));await waitFor(()=>expect(preview).toHaveBeenLastCalledWith("workspace-sync","c","o",2,expect.any(String),expect.objectContaining({aspect_ratio:"1:1",subtitle_mode:"burned"})));
});
it("只有明确请求批量预览才使用统一设置与逐条画幅覆盖",async()=>{
  const api=await import("./api");const settingsApi=await import("./exportSettingsApi");
  vi.mocked(api.getHighlights).mockResolvedValue({asset_id:"a",collection_id:"c",notes:[],brief:{preset:"podcast_highlights",count:1,min_ms:null,max_ms:null,hook_ms:null,instructions:"",max_source_overlap:1},outputs:[{output_id:"o",title:"批量预览",reason:"",revision:1,duration_ms:2000,clips:[]}]});
  vi.mocked(settingsApi.getExportDraft).mockImplementation(async route=>({source:"saved",draft:route.includes("/outputs/")?settingsApi.defaultExportDraft():{...settingsApi.defaultExportDraft(),settings_source:"uniform",options:{...settingsApi.defaultExportOptions(),aspect_ratio:"9:16",subtitle_mode:"burned"},overrides:{o:{aspect_ratio:"1:1",resolution:720,fit:"crop",crop_left:10}}}}));
  vi.spyOn(api,"recoverOutputPreview").mockResolvedValue(null);const preview=vi.spyOn(api,"startOutputPreview").mockResolvedValue({task_id:"batch",status:"pending",error:null,result:null});const view=render(<OutputWorkspace project="workspace-batch" collection="c" output="o"/>);
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成成片预览"})).toBeEnabled());expect(preview).not.toHaveBeenCalled();view.rerender(<OutputWorkspace project="workspace-batch" collection="c" output="o" batchPreviewRequest={{output:"o",id:"explicit"}}/>);await waitFor(()=>expect(preview).toHaveBeenLastCalledWith("workspace-batch","c","o",1,expect.any(String),expect.objectContaining({aspect_ratio:"1:1",resolution:720,fit:"crop",crop_left:10,subtitle_mode:"burned"})));
});

it("上层导出预设保存字幕新版本，后续独立编辑沿用作品设置",async()=>{
  const api=await import("./api");const exports=await import("./exportSettingsApi");const {defaultSubtitleSettings}=await import("./SubtitleAppearanceControls");const layout=defaultSubtitleSettings();layout.subtitle_style={...layout.subtitle_style!,source_size:82,translation_size:46,text_color:"#ffcc00"};
  const data={asset_id:"a",collection_id:"full",notes:[],brief:{} as import("./api").HighlightResult["brief"],outputs:[{output_id:"o",title:"预设作品",reason:"完整",revision:1,duration_ms:2000,clips:[]}]};
  vi.mocked(api.getHighlights).mockResolvedValue(data);vi.mocked(exports.listExportPresets).mockResolvedValue([{preset_id:"full",name:"完整成片",options:{...exports.defaultExportOptions(),aspect_ratio:"9:16",subtitle_mode:"burned",subtitle_settings:layout},created_at:"",updated_at:""}]);
  const save=vi.spyOn(api,"saveOutputSubtitleSettings").mockResolvedValue({...data,outputs:[{...data.outputs[0],revision:2,...layout}]});
  const preview=vi.spyOn(api,"startOutputPreview");
  render(<OutputWorkspace project="preset-project" collection="full" output="o"/>);await screen.findByRole("option",{name:"完整成片"});
  expect(screen.getByRole("region",{name:"成片导出预设"}).querySelector('[role="tabpanel"]')).toBeNull();
  fireEvent.click(screen.getByRole("tab",{name:"字幕设置"}));fireEvent.change(screen.getByLabelText("导出预设"),{target:{value:"full"}});await waitFor(()=>expect(screen.getByText("应用预设")).toBeEnabled());fireEvent.click(screen.getByText("应用预设"));
  await waitFor(()=>expect(save).toHaveBeenCalledWith("preset-project","full","o",1,layout));await screen.findByText(/已应用.*包含完整字幕设置/);
  expect(screen.getByLabelText("原文字号")).toHaveValue(82);expect(screen.getByLabelText("译文字号")).toHaveValue(46);
  expect(exports.saveExportDraft).toHaveBeenCalledWith(expect.stringContaining("preset-project"),expect.objectContaining({options:expect.objectContaining({subtitle_settings:null,aspect_ratio:"9:16",subtitle_mode:"burned"})}));
  expect(preview).not.toHaveBeenCalled();fireEvent.change(screen.getByLabelText("原文字号"),{target:{value:"84"}});await waitFor(()=>expect(screen.getByText("应用预设")).toBeDisabled());expect(screen.getByText("另存为预设")).toBeDisabled();
});

it("保存一句只清理该句草稿，其他原文和译文仍可继续保存",async()=>{
  const api=await import("./api");
  const data=subtitleFixture();
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const firstSaved={...data,outputs:[{...data.outputs[0],revision:2,clips:data.outputs[0].clips.map(clip=>clip.instance_id==="first"?{...clip,text:"Unsaved first draft",translation_text:"未保存的first译文"}:clip)}]};
  const allSaved={...firstSaved,outputs:[{...firstSaved.outputs[0],revision:3,clips:firstSaved.outputs[0].clips.map(clip=>clip.instance_id==="second"?{...clip,text:"Unsaved second draft",translation_text:"未保存的second译文"}:clip)}]};
  const save=vi.spyOn(api,"editOutputItem").mockResolvedValueOnce(firstSaved).mockResolvedValueOnce(allSaved);
  const onDirty=vi.fn();
  render(<OutputWorkspace project="subtitle-save" collection="c" output="o" onDirty={onDirty}/>);
  await openSubtitleDrafts();
  fireEvent.click(subtitleCard("first").getByRole("button",{name:"保存字幕"}));
  await waitFor(()=>expect(subtitleCard("first").getByRole("button",{name:"保存字幕"})).toBeDisabled());
  expect(screen.getByLabelText("字幕 second")).toHaveValue("Unsaved second draft");
  expect(screen.getByLabelText("译文 second")).toHaveValue("未保存的second译文");
  expect(subtitleCard("second").getByRole("button",{name:"保存字幕"})).toBeEnabled();
  expect(screen.getByRole("tab",{name:/逐句编辑/})).toHaveTextContent("未保存");
  expect(onDirty).toHaveBeenLastCalledWith(true);
  expect(screen.getByRole("button",{name:"生成成片预览"})).toBeDisabled();
  fireEvent.click(subtitleCard("second").getByRole("button",{name:"保存字幕"}));
  await waitFor(()=>expect(save).toHaveBeenLastCalledWith("subtitle-save","c","o","second",{display_text:"Unsaved second draft",translation_text:"未保存的second译文"}));
  await waitFor(()=>expect(onDirty).toHaveBeenLastCalledWith(false));
  expect(subtitleCard("second").getByRole("button",{name:"保存字幕"})).toBeDisabled();
});

it("保存失败保留所有字幕草稿，成功后使用服务端保存的文字",async()=>{
  const api=await import("./api");
  const data=subtitleFixture();
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const updated={...data,outputs:[{...data.outputs[0],revision:2,clips:data.outputs[0].clips.map(clip=>clip.instance_id==="first"?{...clip,text:"Canonical first",translation_text:"已保存译文"}:clip)}]};
  const save=vi.spyOn(api,"editOutputItem").mockRejectedValueOnce(new Error("磁盘不可写")).mockResolvedValueOnce(updated);
  render(<OutputWorkspace project="subtitle-failure" collection="c" output="o"/>);
  await openSubtitleDrafts();
  fireEvent.click(subtitleCard("first").getByRole("button",{name:"保存字幕"}));
  expect(await subtitleCard("first").findByRole("alert")).toHaveTextContent("磁盘不可写");
  for(const id of ["first","second"]){
    expect(screen.getByLabelText(`字幕 ${id}`)).toHaveValue(`Unsaved ${id} draft`);
    expect(screen.getByLabelText(`译文 ${id}`)).toHaveValue(`未保存的${id}译文`);
  }
  fireEvent.click(subtitleCard("first").getByRole("button",{name:"保存字幕"}));
  await waitFor(()=>expect(screen.getByLabelText("字幕 first")).toHaveValue("Canonical first"));
  expect(screen.getByLabelText("译文 first")).toHaveValue("已保存译文");
  expect(screen.getByLabelText("字幕 second")).toHaveValue("Unsaved second draft");
  expect(save).toHaveBeenCalledTimes(2);
});

it("保存范围只重置受影响句子的草稿，并同步重新提取的字幕",async()=>{
  const api=await import("./api");
  const data=subtitleFixture();
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const updated={...data,outputs:[{...data.outputs[0],revision:2,clips:data.outputs[0].clips.map(clip=>clip.instance_id==="first"?{...clip,start_ms:500,text:"Re-extracted first",translation_text:undefined}:clip)}]};
  const save=vi.spyOn(api,"saveOutputRanges").mockRejectedValueOnce(new Error("版本冲突")).mockResolvedValueOnce(updated);
  render(<OutputWorkspace project="subtitle-range" collection="c" output="o"/>);
  await openSubtitleDrafts();
  fireEvent.change(screen.getByLabelText("开始 first"),{target:{value:"0.5"}});
  fireEvent.click(screen.getByRole("button",{name:"保存修改"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("版本冲突");
  expect(screen.getByLabelText("字幕 first")).toHaveValue("Unsaved first draft");
  expect(screen.getByLabelText("译文 first")).toHaveValue("未保存的first译文");
  fireEvent.click(screen.getByRole("button",{name:"保存修改"}));
  await waitFor(()=>expect(screen.getByLabelText("字幕 first")).toHaveValue("Re-extracted first"));
  expect(screen.getByLabelText("译文 first")).toHaveValue("");
  expect(subtitleCard("first").getByRole("button",{name:"保存字幕"})).toBeDisabled();
  expect(screen.getByLabelText("字幕 second")).toHaveValue("Unsaved second draft");
  expect(screen.getByLabelText("译文 second")).toHaveValue("未保存的second译文");
  expect(save).toHaveBeenLastCalledWith("subtitle-range","c","o",1,[{instance_id:"first",source_start_ms:500,source_end_ms:2000}]);
});

it.each(["手动", "自动"])("%s分句清理被替换句子的草稿，保留其他句子",async mode=>{
  const api=await import("./api");
  const data=subtitleFixture();
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const parts=[{text:"First",start_ms:0,end_ms:1000},{text:"part",start_ms:1000,end_ms:2000}];
  const clips=[...parts.map((part,index)=>({...data.outputs[0].clips[0],...part,instance_id:`first-split-${index}`,translation_text:undefined})),data.outputs[0].clips[1]];
  const updated={...data,outputs:[{...data.outputs[0],revision:2,clips}]};
  const split=vi.spyOn(api,mode==="手动"?"applyManualSplit":"splitOutputSentences").mockResolvedValue(updated);
  vi.spyOn(api,"previewManualSplit").mockResolvedValue({ranges:parts});
  vi.spyOn(window,"confirm").mockReturnValue(true);
  const onDirty=vi.fn();
  render(<OutputWorkspace project="subtitle-split" collection="c" output="o" onDirty={onDirty}/>);
  await openSubtitleDrafts();
  if(mode==="手动"){
    fireEvent.change(screen.getByLabelText("字幕 first"),{target:{value:"First\npart"}});
    fireEvent.click(subtitleCard("first").getByRole("button",{name:"预览分句时间"}));
    fireEvent.click(await subtitleCard("first").findByRole("button",{name:"确认分句"}));
  }else{
    fireEvent.click(screen.getByRole("button",{name:"按句拆分片段"}));
  }
  await screen.findByLabelText("编辑字幕 first-split-0");
  expect(split).toHaveBeenCalledOnce();
  expect(screen.queryByLabelText("字幕 first")).not.toBeInTheDocument();
  expect(screen.getByLabelText("字幕 first-split-0")).toHaveValue("First");
  expect(screen.getByLabelText("译文 first-split-0")).toHaveValue("");
  expect(screen.getByLabelText("字幕 second")).toHaveValue("Unsaved second draft");
  expect(screen.getByLabelText("译文 second")).toHaveValue("未保存的second译文");
  // Reverting the surviving drafts must leave no orphaned draft for the removed ID.
  fireEvent.change(screen.getByLabelText("字幕 second"),{target:{value:"Second"}});
  fireEvent.change(screen.getByLabelText("译文 second"),{target:{value:"第二句"}});
  await waitFor(()=>expect(onDirty).toHaveBeenLastCalledWith(false));
});

it("历史版本只显示已保存字幕，切回当前版本恢复草稿",async()=>{
  const api=await import("./api");
  const data=subtitleFixture();
  data.outputs[0].revision=2;
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  vi.spyOn(api,"getOutputVersions").mockResolvedValue([
    {...data.outputs[0],revision:1,clips:data.outputs[0].clips.map(clip=>({...clip,text:`Historical ${clip.instance_id}`,translation_text:"历史译文"}))},
    data.outputs[0],
  ]);
  render(<OutputWorkspace project="subtitle-history" collection="c" output="o"/>);
  await openSubtitleDrafts();
  fireEvent.click(screen.getByText("版本记录"));
  fireEvent.click(screen.getByRole("button",{name:"查看版本"}));
  fireEvent.change(await screen.findByLabelText("预览版本"),{target:{value:"1"}});
  expect(screen.getByLabelText("字幕 first")).toHaveValue("Historical first");
  expect(screen.getByLabelText("译文 second")).toHaveValue("历史译文");
  expect(screen.getByLabelText("字幕 second")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("预览版本"),{target:{value:"2"}});
  expect(screen.getByLabelText("字幕 first")).toHaveValue("Unsaved first draft");
  expect(screen.getByLabelText("译文 second")).toHaveValue("未保存的second译文");
  expect(screen.getByLabelText("字幕 second")).toBeEnabled();
});

it("作品切换时相同 instance_id 的字幕草稿互不覆盖",async()=>{
  const api=await import("./api");
  const data=subtitleFixture();
  const other={...data.outputs[0],output_id:"other",title:"其他作品",clips:data.outputs[0].clips.map(clip=>({...clip,text:`Other ${clip.instance_id}`,translation_text:"其他译文"}))};
  vi.mocked(api.getHighlights).mockResolvedValue({...data,outputs:[data.outputs[0],other]});
  const view=render(<OutputWorkspace project="subtitle-scope" collection="c" output="o"/>);
  await openSubtitleDrafts();
  view.rerender(<OutputWorkspace project="subtitle-scope" collection="c" output="other"/>);
  expect(screen.getByLabelText("字幕 first")).toHaveValue("Other first");
  expect(screen.getByLabelText("译文 second")).toHaveValue("其他译文");
  fireEvent.change(screen.getByLabelText("字幕 first"),{target:{value:"Other draft"}});
  view.rerender(<OutputWorkspace project="subtitle-scope" collection="c" output="o"/>);
  expect(screen.getByLabelText("字幕 first")).toHaveValue("Unsaved first draft");
  expect(screen.getByLabelText("译文 second")).toHaveValue("未保存的second译文");
  view.rerender(<OutputWorkspace project="subtitle-scope" collection="c" output="other"/>);
  expect(screen.getByLabelText("字幕 first")).toHaveValue("Other draft");
});

it.each(["删除", "排序", "字幕设置"])("%s创建新版本时保留逐句原文和译文草稿",async action=>{
  const api=await import("./api");
  const data=subtitleFixture();
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const clips=action==="删除"?data.outputs[0].clips.map(clip=>clip.instance_id==="first"?{...clip,deleted:true}:clip):action==="排序"?[...data.outputs[0].clips].reverse():data.outputs[0].clips;
  const updated={...data,outputs:[{...data.outputs[0],revision:2,clips,subtitle_style:{...api.defaultSubtitleStyle(),source_size:72}}]};
  const save=action==="删除"?vi.spyOn(api,"editOutputItem").mockResolvedValue(updated):action==="排序"?vi.spyOn(api,"reorderOutput").mockResolvedValue(updated):vi.spyOn(api,"saveOutputSubtitleSettings").mockResolvedValue(updated);
  render(<OutputWorkspace project="subtitle-revision" collection="c" output="o"/>);
  await openSubtitleDrafts();
  if(action==="字幕设置"){
    fireEvent.click(screen.getByRole("tab",{name:"字幕设置"}));
    fireEvent.change(screen.getByLabelText("原文字号"),{target:{value:"72"}});
    fireEvent.click(screen.getByRole("button",{name:"保存字幕设置"}));
    await screen.findByText(/^v2 ·/);
    expect(screen.getByLabelText("原文字号")).toHaveValue(72);
    fireEvent.click(screen.getByRole("tab",{name:/逐句编辑/}));
  }else{
    fireEvent.click(subtitleCard("first").getByRole("button",{name:action==="删除"?"删除片段":"下移"}));
    await screen.findByText(/^v2 ·/);
  }
  expect(save).toHaveBeenCalledOnce();
  for(const id of ["first","second"]){
    expect(screen.getByLabelText(`字幕 ${id}`)).toHaveValue(`Unsaved ${id} draft`);
    expect(screen.getByLabelText(`译文 ${id}`)).toHaveValue(`未保存的${id}译文`);
  }
});

it("取消开场预告导致编辑器换区域时保留该实例的字幕草稿",async()=>{
  const api=await import("./api");
  const data:import("./api").HighlightResult=subtitleFixture();
  data.outputs[0].clips[0].role="hook";
  vi.mocked(api.getHighlights).mockResolvedValue(data);
  const updated={...data,outputs:[{...data.outputs[0],revision:2,clips:data.outputs[0].clips.map(clip=>({...clip,role:"body" as const}))}]};
  const save=vi.spyOn(api,"reorderOutput").mockResolvedValue(updated);
  render(<OutputWorkspace project="subtitle-role" collection="c" output="o"/>);
  await screen.findByLabelText("编辑字幕 first");
  fireEvent.click(screen.getByRole("tab",{name:"开场预告"}));
  fireEvent.click(screen.getByLabelText("编辑字幕 first"));
  fireEvent.change(screen.getByLabelText("字幕 first"),{target:{value:"Hook draft"}});
  fireEvent.change(screen.getByLabelText("译文 first"),{target:{value:"预告译文草稿"}});
  fireEvent.click(subtitleCard("first").getByRole("button",{name:"取消开场预告"}));
  await screen.findByText("当前没有开场预告。");
  fireEvent.click(screen.getByRole("tab",{name:/逐句编辑/}));
  expect(save).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("字幕 first")).toHaveValue("Hook draft");
  expect(screen.getByLabelText("译文 first")).toHaveValue("预告译文草稿");
  fireEvent.click(screen.getByLabelText("编辑字幕 first"));
  expect(subtitleCard("first").getByRole("button",{name:"保存字幕"})).toBeEnabled();
});
