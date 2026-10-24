import {beforeEach,expect,it,vi} from "vitest";
import {render,screen,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {MinimalPreview} from "./MinimalPreview";
import {defaultExportOptions,exportSettingsRoute,getExportDraft,type ExportOptions} from "./exportSettingsApi";
import {recoverOutputPreview,startOutputPreview,type HighlightResult,type OutputExportTask} from "./api";

vi.mock("./api",async original=>({...await original<typeof import("./api")>(),recoverOutputPreview:vi.fn(),startOutputPreview:vi.fn(),readOutputExport:vi.fn()}));
vi.mock("./exportSettingsApi",async original=>({...await original<typeof import("./exportSettingsApi")>(),getExportDraft:vi.fn()}));

const result:HighlightResult={collection_id:"c",asset_id:"a",brief:{preset:"podcast_highlights",count:1,min_ms:1000,max_ms:2000,hook_ms:null,max_source_overlap:1},notes:[],outputs:[{output_id:"o",title:"AI 的未来",reason:"主题完整",revision:2,duration_ms:1800,clips:[]}],selected_output_ids:["o"]};
const options:ExportOptions={...defaultExportOptions(),aspect_ratio:"9:16",subtitle_mode:"burned",audio_fade_ms:100};
const task:OutputExportTask={task_id:"preview",status:"succeeded",error:null,result:{output_id:"o",revision:2,media_url:"/rendered.mp4",subtitle_url:"/rendered.srt",width:1080,height:1920,duration_ms:1800}};
beforeEach(()=>{
  vi.clearAllMocks();
  vi.mocked(getExportDraft).mockResolvedValue({source:"saved",draft:{options,overrides:{},preset_id:null,preset_name:null}});
  vi.mocked(recoverOutputPreview).mockResolvedValue(null);
  vi.mocked(startOutputPreview).mockResolvedValue(task);
});

it("初始只试听，显式点击才按已保存的作品设置生成成片预览",async()=>{
  const user=userEvent.setup();render(<MinimalPreview project="p" result={result} output={result.outputs[0]}/>);
  expect(screen.getByLabelText("快速预览 · AI 的未来")).toBeInTheDocument();
  expect(getExportDraft).not.toHaveBeenCalled();expect(startOutputPreview).not.toHaveBeenCalled();expect(recoverOutputPreview).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button",{name:"成片预览"}));
  expect(await screen.findByLabelText("成片预览 · AI 的未来")).toHaveAttribute("src","/rendered.mp4");
  expect(getExportDraft).toHaveBeenCalledWith(exportSettingsRoute("p","c","o"),expect.any(AbortSignal));
  expect(startOutputPreview).toHaveBeenCalledWith("p","c","o",2,expect.any(String),options);
  expect(screen.getByText(/9:16 · 1080×1920 · 烧录字幕/)).toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"快速预览"}));
  expect(screen.getByLabelText("快速预览 · AI 的未来")).toBeInTheDocument();
  vi.mocked(recoverOutputPreview).mockResolvedValue(task);
  await user.click(screen.getByRole("button",{name:"成片预览"}));
  expect(await screen.findByLabelText("成片预览 · AI 的未来")).toHaveAttribute("src","/rendered.mp4");
  expect(startOutputPreview).toHaveBeenCalledTimes(1);
});

it("软字幕预览保留播放器字幕轨",async()=>{
  const user=userEvent.setup();vi.mocked(getExportDraft).mockResolvedValue({source:"saved",draft:{options:{...options,subtitle_mode:"soft"},overrides:{},preset_id:null,preset_name:null}});
  vi.mocked(startOutputPreview).mockResolvedValue({...task,result:{...task.result!,subtitle_track_url:"/rendered.vtt"}});
  const view=render(<MinimalPreview project="p" result={result} output={result.outputs[0]}/>);
  await user.click(screen.getByRole("button",{name:"成片预览"}));await screen.findByLabelText("成片预览 · AI 的未来");
  expect(view.container.querySelector("track")).toHaveAttribute("src","/rendered.vtt");
  expect(startOutputPreview).toHaveBeenCalledWith("p","c","o",2,expect.any(String),expect.objectContaining({subtitle_mode:"soft"}));
});

it("设置读取失败不使用默认配置渲染，可再次点击重试",async()=>{
  const user=userEvent.setup();vi.mocked(getExportDraft).mockRejectedValueOnce(new Error("设置暂时无法读取"));
  render(<MinimalPreview project="p" result={result} output={result.outputs[0]}/>);
  await user.click(screen.getByRole("button",{name:"成片预览"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("设置暂时无法读取");expect(startOutputPreview).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button",{name:"成片预览"}));
  expect(await screen.findByLabelText("成片预览 · AI 的未来")).toHaveAttribute("src","/rendered.mp4");expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("作品版本改变时提示更新，点击更新后重新读取设置并使用新版本",async()=>{
  const user=userEvent.setup();const view=render(<MinimalPreview project="p" result={result} output={result.outputs[0]}/>);
  await user.click(screen.getByRole("button",{name:"成片预览"}));await screen.findByLabelText("成片预览 · AI 的未来");
  view.rerender(<MinimalPreview project="p" result={result} output={{...result.outputs[0],revision:3}}/>);
  expect(screen.getByText("作品版本已变化，请更新成片预览。")).toBeInTheDocument();
  vi.mocked(getExportDraft).mockResolvedValue({source:"saved",draft:{options:{...options,aspect_ratio:"1:1"},overrides:{},preset_id:null,preset_name:null}});
  vi.mocked(startOutputPreview).mockResolvedValue({...task,task_id:"new",result:{...task.result!,revision:3,media_url:"/new.mp4"}});
  await user.click(screen.getByRole("button",{name:"更新成片预览"}));
  await waitFor(()=>expect(screen.getByLabelText("成片预览 · AI 的未来")).toHaveAttribute("src","/new.mp4"));
  expect(startOutputPreview).toHaveBeenLastCalledWith("p","c","o",3,expect.any(String),expect.objectContaining({aspect_ratio:"1:1"}));
});
