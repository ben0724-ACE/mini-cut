import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BatchExport } from "./BatchExport";
import { startOutputExport, startOutputExportBatch } from "./api";
vi.mock("./api",async original=>({...await original<typeof import("./api")>(),listSubtitleFonts:vi.fn().mockResolvedValue([{id:"heiti",name:"黑体"},{id:"songti",name:"宋体"}]),recoverOutputExport:vi.fn().mockResolvedValue(null),readOutputExport:vi.fn(),startOutputExport:vi.fn().mockResolvedValue({task_id:"retry",status:"succeeded",result:{media_url:"/retry",subtitle_url:"/srt"},error:null}),startOutputExportBatch:vi.fn().mockResolvedValue([{task_id:"a",status:"succeeded",result:{media_url:"/good",subtitle_url:"/srt"},error:null},{task_id:"b",status:"failed",result:null,error:"坏片段"}])}));
vi.mock("./exportSettingsApi",async original=>{const actual=await original<typeof import("./exportSettingsApi")>();return {...actual,getExportDraft:vi.fn().mockImplementation(async()=>({source:"default",draft:actual.defaultExportDraft()})),saveExportDraft:vi.fn().mockImplementation(async(_route,draft)=>({source:"saved",draft})),listExportPresets:vi.fn().mockResolvedValue([])};});
beforeEach(()=>localStorage.clear());

it("批量部分失败只重试失败作品，失败不能下载",async()=>{
  render(<BatchExport project="p" collection="c" outputs={[{output_id:"a",title:"A",revision:1},{output_id:"b",title:"B",revision:1}]} selected={["a","b"]} disabled={false} />);
  await waitFor(()=>expect(screen.getByRole("button",{name:"导出已选作品"})).toBeEnabled());
  await userEvent.click(screen.getByRole("button",{name:"导出已选作品"}));
  expect(await screen.findByRole("link",{name:"下载 A"})).toHaveAttribute("href","/good");
  expect(screen.queryByRole("link",{name:"下载 B"})).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"重试 B"}));
  expect(startOutputExport).toHaveBeenCalledWith("p","c","b",1,expect.anything(),expect.any(String));
  expect(await screen.findByRole("link",{name:"下载 B"})).toHaveAttribute("href","/retry");
});
it("批量统一画幅允许单条覆盖",async()=>{
  render(<BatchExport project="p" collection="c" outputs={[{output_id:"a",title:"A",revision:1}]} selected={["a"]} disabled={false} />);
  await userEvent.click(screen.getByLabelText("统一使用批量设置／预设"));
  await userEvent.click(screen.getByText("逐条画幅覆盖"));
  await userEvent.selectOptions(screen.getByLabelText("批量比例"),"16:9");
  await userEvent.click(screen.getByLabelText("单独设置 A"));
  await userEvent.selectOptions(screen.getByLabelText("A比例"),"9:16");
  await waitFor(()=>expect(screen.getByRole("button",{name:"导出已选作品"})).toBeEnabled());
  await userEvent.click(screen.getByRole("button",{name:"导出已选作品"}));
  expect(startOutputExportBatch).toHaveBeenLastCalledWith("p","c",expect.anything(),expect.objectContaining({aspect_ratio:"16:9"}),expect.any(String),{},{a:expect.objectContaining({aspect_ratio:"9:16",resolution:1080,fit:"pad"})});
});
it("批量提交后将所有任务交给结果页导航",async()=>{
  const onSubmitted=vi.fn();
  render(<BatchExport project="p" collection="c" outputs={[{output_id:"a",title:"A",revision:1},{output_id:"b",title:"B",revision:1}]} selected={["a","b"]} disabled={false} onSubmitted={onSubmitted} />);
  await waitFor(()=>expect(screen.getByRole("button",{name:"导出已选作品"})).toBeEnabled());
  await userEvent.click(screen.getByRole("button",{name:"导出已选作品"}));
  expect(onSubmitted).toHaveBeenCalledWith([{outputId:"a",taskId:"a"},{outputId:"b",taskId:"b"}]);
});
it("恢复已有批量导出后可重新进入结果页",async()=>{
  const api=await import("./api");
  vi.mocked(api.recoverOutputExport).mockResolvedValueOnce({task_id:"saved-a",status:"succeeded",result:{output_id:"a",revision:1,duration_ms:1000,media_url:"/saved.mp4",subtitle_url:"/saved.srt"},error:null});
  const onSubmitted=vi.fn();
  render(<BatchExport project="p" collection="c" outputs={[{output_id:"a",title:"A",revision:1}]} selected={["a"]} disabled={false} onSubmitted={onSubmitted} />);
  await userEvent.click(await screen.findByRole("button",{name:"导出结果"}));
  expect(onSubmitted).toHaveBeenCalledWith([{outputId:"a",taskId:"saved-a"}]);
});
it("恢复批量逐条覆盖，应用预设保留覆盖，清除后使用统一画幅",async()=>{
  const settingsApi=await import("./exportSettingsApi");const {waitFor}=await import("@testing-library/react");
  vi.mocked(settingsApi.getExportDraft).mockImplementation(async (route):Promise<import("./exportSettingsApi").ExportDraftResponse>=>({source:"saved",draft:route.includes("/outputs/")?settingsApi.defaultExportDraft():{...settingsApi.defaultExportDraft(),settings_source:"uniform",overrides:{a:{aspect_ratio:"1:1",resolution:720,fit:"pad"}}}}));
  vi.mocked(settingsApi.listExportPresets).mockResolvedValueOnce([{preset_id:"vertical",name:"竖屏",options:{...settingsApi.defaultExportOptions(),aspect_ratio:"9:16",subtitle_mode:"burned"},created_at:"now",updated_at:"now"}]);
  render(<BatchExport project="batch-restore" collection="c" outputs={[{output_id:"a",title:"A",revision:1}]} selected={["a"]} disabled={false}/>);
  await screen.findByRole("option",{name:"竖屏"});await userEvent.selectOptions(screen.getByLabelText("导出预设"),"vertical");await userEvent.click(screen.getByRole("button",{name:"应用预设"}));
  expect(screen.getByLabelText("批量比例")).toHaveValue("9:16");expect(screen.getByLabelText("单独设置 A")).toBeChecked();expect(screen.getByLabelText("A比例")).toHaveValue("1:1");
  await userEvent.click(screen.getByRole("button",{name:"清除全部逐条覆盖"}));expect(screen.getByLabelText("单独设置 A")).not.toBeChecked();await waitFor(()=>expect(settingsApi.saveExportDraft).toHaveBeenLastCalledWith(expect.any(String),expect.objectContaining({overrides:{},options:expect.objectContaining({aspect_ratio:"9:16",subtitle_mode:"burned"})})));
});

it("默认沿用每条作品设置，统一配置列出差异且不会覆盖作品设置",async()=>{
  const settingsApi=await import("./exportSettingsApi");const {within,waitFor}=await import("@testing-library/react");
  const first={...settingsApi.defaultExportOptions(),aspect_ratio:"9:16" as const,resolution:720 as const,subtitle_mode:"burned" as const,crop_bottom:8};
  const second={...settingsApi.defaultExportOptions(),aspect_ratio:"1:1" as const};
  vi.mocked(settingsApi.getExportDraft).mockImplementation(async (route):Promise<import("./exportSettingsApi").ExportDraftResponse>=>({source:"saved",draft:{...settingsApi.defaultExportDraft(),options:route.endsWith("/outputs/a/export-settings")?first:route.endsWith("/outputs/b/export-settings")?second:{...second,aspect_ratio:"16:9"},overrides:route.includes("/outputs/")?{}:{a:{aspect_ratio:"4:5",resolution:1080,fit:"pad"}}}}));
  vi.mocked(settingsApi.saveExportDraft).mockClear();const onPreview=vi.fn();render(<BatchExport project="per-output" collection="c" outputs={[{output_id:"a",title:"A",revision:1},{output_id:"b",title:"B",revision:2}]} selected={["a","b"]} disabled={false} onPreview={onPreview}/>);
  await waitFor(()=>expect(screen.getByRole("button",{name:"导出已选作品"})).toBeEnabled());expect(screen.getByLabelText("沿用各作品设置")).toBeChecked();
  const a=within(screen.getByRole("article",{name:"批量配置 A"}));const b=within(screen.getByRole("article",{name:"批量配置 B"}));expect(a.getByText("9:16 · 720×1280 · 烧录字幕")).toBeInTheDocument();expect(b.getByText("1:1 · 1080×1080 · 软字幕")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"预览 A 的批量效果"}));expect(onPreview).toHaveBeenCalledWith("a");
  await waitFor(()=>expect(screen.getByRole("button",{name:"导出已选作品"})).toBeEnabled());
  await userEvent.click(screen.getByRole("button",{name:"导出已选作品"}));expect(startOutputExportBatch).toHaveBeenLastCalledWith("per-output","c",expect.anything(),expect.anything(),expect.any(String),{},{a:first,b:second});
  await userEvent.click(screen.getByLabelText("统一使用批量设置／预设"));expect(a.getByText("4:5 · 1080×1350 · 软字幕")).toBeInTheDocument();expect(b.getByText("16:9 · 1920×1080 · 软字幕")).toBeInTheDocument();expect(screen.getAllByText("统一配置：与作品设置不同")).toHaveLength(2);
  expect(vi.mocked(settingsApi.saveExportDraft).mock.calls.every(([route])=>!route.includes("/outputs/"))).toBe(true);
  await userEvent.click(screen.getByLabelText("沿用各作品设置"));expect(a.getByText("9:16 · 720×1280 · 烧录字幕")).toBeInTheDocument();expect(b.getByText("1:1 · 1080×1080 · 软字幕")).toBeInTheDocument();
});

it("批量完整预设传递独立字体与效果，关闭统一后沿用作品设置",async()=>{
  const settingsApi=await import("./exportSettingsApi");const {defaultSubtitleSettings}=await import("./SubtitleAppearanceControls");const layout=defaultSubtitleSettings();layout.subtitle_style={...layout.subtitle_style!,source_font_id:"heiti",translation_font_id:"songti",source_size:82,text_color:"#ffcc00",background_enabled:true};
  vi.mocked(settingsApi.getExportDraft).mockResolvedValue({source:"saved",draft:settingsApi.defaultExportDraft()});vi.mocked(settingsApi.listExportPresets).mockResolvedValue([{preset_id:"full",name:"完整字体",options:{...settingsApi.defaultExportOptions(),subtitle_mode:"burned",subtitle_settings:layout},created_at:"",updated_at:""}]);
  vi.mocked(startOutputExportBatch).mockClear();render(<BatchExport project="full-batch" collection="full" outputs={[{output_id:"a",title:"A",revision:3}]} selected={["a"]} disabled={false}/>);
  await userEvent.click(screen.getByLabelText("统一使用批量设置／预设"));await screen.findByRole("option",{name:"完整字体"});await userEvent.selectOptions(screen.getByLabelText("导出预设"),"full");await userEvent.click(screen.getByText("应用预设"));await userEvent.click(screen.getByText("批量字幕设置"));
  expect(screen.getByLabelText("原文字体")).toHaveValue("heiti");expect(screen.getByLabelText("译文字体")).toHaveValue("songti");expect(screen.getByLabelText("原文字号")).toHaveValue(82);expect(screen.getByLabelText("字幕背景框")).toBeChecked();
  await waitFor(()=>expect(screen.getByText("导出已选作品")).toBeEnabled());await userEvent.click(screen.getByText("导出已选作品"));expect(startOutputExportBatch).toHaveBeenLastCalledWith("full-batch","full",[{output_id:"a",title:"A",revision:3}],expect.objectContaining({subtitle_settings:layout}),expect.any(String),{},{a:expect.objectContaining({subtitle_settings:layout})});
  expect(settingsApi.saveExportDraft).not.toHaveBeenCalledWith(expect.stringContaining("full-batch/highlights/full/outputs/"),expect.anything());
  await userEvent.click(screen.getByLabelText("沿用各作品设置"));await waitFor(()=>expect(screen.getByText("导出已选作品")).toBeEnabled());await userEvent.click(screen.getByText("导出已选作品"));expect(startOutputExportBatch).toHaveBeenLastCalledWith("full-batch","full",expect.anything(),expect.anything(),expect.any(String),{},{a:expect.not.objectContaining({subtitle_settings:layout})});
});
