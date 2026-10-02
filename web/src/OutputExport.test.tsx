import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OutputExport } from "./OutputExport";
vi.mock("./api", () => ({recoverOutputExport: vi.fn().mockResolvedValue(null), startOutputExport: vi.fn().mockRejectedValue(new Error("导出失败")), readOutputExport: vi.fn(), cancelOutputExport: vi.fn()}));
vi.mock("./exportSettingsApi",async original=>{const actual=await original<typeof import("./exportSettingsApi")>();return {...actual,getExportDraft:vi.fn().mockImplementation(async()=>({source:"default",draft:actual.defaultExportDraft()})),saveExportDraft:vi.fn().mockImplementation(async(_route,draft)=>({source:"saved",draft})),listExportPresets:vi.fn().mockResolvedValue([])};});
beforeEach(()=>localStorage.clear());

it("音频处理默认关闭，失败不显示下载", async () => {
  render(<OutputExport project="p" collection="c" output="o" revision={1} />);
  expect(await screen.findByText("淡入淡出 0 毫秒 · 降噪关闭")).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name:"导出当前作品"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("导出失败");
  expect(screen.queryByRole("link", {name:"下载视频"})).not.toBeInTheDocument();
});
it("恢复失败后可重新查询，不在恢复期间提交重复导出", async () => {
  const api=await import("./api");
  vi.mocked(api.recoverOutputExport).mockRejectedValueOnce(new Error("暂时离线")).mockResolvedValueOnce({task_id:"done",status:"succeeded",result:{revision:1,output_id:"o",media_url:"/result.mp4",subtitle_url:"/result.srt",duration_ms:1000},error:null});
  render(<OutputExport project="p" collection="c" output="o" revision={1} />);
  expect(screen.getByRole("button",{name:"导出当前作品"})).toBeDisabled();
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时离线");
  await userEvent.click(screen.getByRole("button",{name:"恢复导出状态"}));
  expect(await screen.findByRole("link",{name:"下载视频"})).toHaveAttribute("href","/result.mp4");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("提交成功后把作品和任务交给结果页导航",async()=>{
  const api=await import("./api");
  vi.mocked(api.recoverOutputExport).mockResolvedValueOnce(null);
  vi.mocked(api.startOutputExport).mockResolvedValueOnce({task_id:"export-1",status:"pending",result:null,error:null});
  const onSubmitted=vi.fn();
  render(<OutputExport project="p" collection="c" output="o" revision={1} onSubmitted={onSubmitted} />);
  await userEvent.click(await screen.findByRole("button",{name:"导出当前作品"}));
  expect(onSubmitted).toHaveBeenCalledWith([{outputId:"o",taskId:"export-1"}]);
});
it("恢复已有导出后可重新进入结果页",async()=>{
  const api=await import("./api");
  vi.mocked(api.recoverOutputExport).mockResolvedValueOnce({task_id:"saved-export",status:"succeeded",result:{revision:1,output_id:"o",media_url:"/saved.mp4",subtitle_url:"/saved.srt",duration_ms:1000},error:null});
  const onSubmitted=vi.fn();
  render(<OutputExport project="p" collection="c" output="o" revision={1} onSubmitted={onSubmitted} />);
  await userEvent.click(await screen.findByRole("button",{name:"导出结果"}));
  expect(onSubmitted).toHaveBeenCalledWith([{outputId:"o",taskId:"saved-export"}]);
});
it("恢复保存的画面设置后按实际配置提交，封面草稿阻止导出",async()=>{
  const settingsApi=await import("./exportSettingsApi");const api=await import("./api");
  vi.mocked(settingsApi.getExportDraft).mockResolvedValueOnce({source:"saved",draft:{...settingsApi.defaultExportDraft(),options:{...settingsApi.defaultExportOptions(),aspect_ratio:"9:16",resolution:720,subtitle_mode:"burned",crop_bottom:12}}});
  vi.mocked(api.recoverOutputExport).mockResolvedValueOnce(null);vi.mocked(api.startOutputExport).mockResolvedValueOnce({task_id:"configured",status:"pending",result:null,error:null});
  const view=render(<OutputExport project="restored" collection="c" output="o" revision={2} disabled cover={<input aria-label="封面草稿"/>}/>);
  expect(await screen.findByText("9:16 · 720×1280 · 烧录字幕")).toBeInTheDocument();expect(screen.getByRole("button",{name:"导出当前作品"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"封面"}));expect(screen.getByLabelText("封面草稿")).toBeVisible();expect(screen.getByRole("button",{name:"导出当前作品"})).toBeVisible();
  view.rerender(<OutputExport project="restored" collection="c" output="o" revision={2} coverVersion={3} cover={<input aria-label="封面草稿"/>}/>);
  await userEvent.click(screen.getByRole("button",{name:"导出当前作品"}));expect(api.startOutputExport).toHaveBeenLastCalledWith("restored","c","o",2,expect.objectContaining({aspect_ratio:"9:16",resolution:720,subtitle_mode:"burned",crop_bottom:12,cover_version:3}),expect.any(String));
});

it("导出只核对设置，调整入口跳回对应编辑区",async()=>{
  const onAdjust=vi.fn();render(<OutputExport project="summary" collection="c" output="o" revision={1} onAdjust={onAdjust}/>);
  await userEvent.click(screen.getByRole("button",{name:"调整画面"}));expect(onAdjust).toHaveBeenLastCalledWith("frame");
  await userEvent.click(screen.getByRole("button",{name:"调整字幕"}));expect(onAdjust).toHaveBeenLastCalledWith("subtitles");expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});

it("取消请求显示普通状态提示，继续查询直到后台确认取消",async()=>{
  const api=await import("./api");
  vi.mocked(api.recoverOutputExport).mockResolvedValueOnce({task_id:"cancelling",status:"running",result:null,error:null});
  vi.mocked(api.cancelOutputExport).mockResolvedValueOnce({task_id:"cancelling",status:"running",result:null,error:null});
  vi.mocked(api.readOutputExport).mockResolvedValue({task_id:"cancelling",status:"cancelled",result:null,error:null});
  render(<OutputExport project="cancel" collection="c" output="o" revision={1}/>);
  await userEvent.click(await screen.findByRole("button",{name:"取消导出"}));
  expect(await screen.findByText("已请求取消，等待后台停止")).toHaveAttribute("role","status");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"正在取消…"})).toBeDisabled();
  await waitFor(()=>expect(screen.getByText("导出状态：已取消")).toBeInTheDocument(),{timeout:2000});
  expect(screen.queryByText("已请求取消，等待后台停止")).not.toBeInTheDocument();
});
