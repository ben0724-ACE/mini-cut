import {beforeEach,expect,it,vi} from "vitest";
import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import {ExportDraftStatus,useExportDraft} from "./useExportDraft";
import * as api from "./exportSettingsApi";
vi.mock("./exportSettingsApi",async original=>({...await original<typeof import("./exportSettingsApi")>(),getExportDraft:vi.fn(),saveExportDraft:vi.fn()}));
function Harness({route}:{route:string}){const state=useExportDraft(route);return <><ExportDraftStatus state={state}/><select aria-label="字幕" disabled={!state.loaded} value={state.draft.options.subtitle_mode} onChange={event=>state.change({...state.draft,options:{...state.draft.options,subtitle_mode:event.target.value as "soft"|"burned"}})}><option value="soft">软</option><option value="burned">烧录</option></select><output aria-label="配置">{JSON.stringify(state.draft)}</output></>;}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(done=>{resolve=done;});return {promise,resolve};}
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();vi.mocked(api.getExportDraft).mockResolvedValue({source:"default",draft:api.defaultExportDraft()});vi.mocked(api.saveExportDraft).mockImplementation(async(_route,draft)=>({source:"saved",draft}));});
it("在途保存按顺序写入最新修改，重新挂载等待保存完成",async()=>{
  const route="/ordered-export";const first=deferred<api.ExportDraftResponse>();let saved=api.defaultExportDraft();
  vi.mocked(api.saveExportDraft).mockImplementationOnce(()=>first.promise).mockImplementation(async(_route,draft)=>{saved=draft;return {source:"saved",draft};});
  vi.mocked(api.getExportDraft).mockImplementation(async()=>({source:"saved",draft:saved}));
  const view=render(<Harness route={route}/>);await waitFor(()=>expect(screen.getByLabelText("字幕")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("字幕"),{target:{value:"burned"}});fireEvent.change(screen.getByLabelText("字幕"),{target:{value:"soft"}});
  expect(api.saveExportDraft).toHaveBeenCalledTimes(1);view.unmount();render(<Harness route={route}/>);
  expect(screen.getByLabelText("字幕")).toBeDisabled();first.resolve({source:"saved",draft:api.defaultExportDraft()});
  await waitFor(()=>expect(screen.getByLabelText("字幕")).toBeEnabled());expect(api.saveExportDraft).toHaveBeenCalledTimes(2);expect(saved.options.subtitle_mode).toBe("soft");expect(localStorage.getItem(`minicut:export-draft:${route}`)).toBeNull();
});
it("保存失败保留本机修改，重新打开自动恢复并重试",async()=>{
  const route="/failed-export";vi.mocked(api.saveExportDraft).mockRejectedValueOnce(new Error("磁盘暂不可写"));
  const view=render(<Harness route={route}/>);await waitFor(()=>expect(screen.getByLabelText("字幕")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("字幕"),{target:{value:"burned"}});await screen.findByText("重试保存导出设置");expect(localStorage.getItem(`minicut:export-draft:${route}`)).toContain('"burned"');
  view.unmount();render(<Harness route={route}/>);await waitFor(()=>expect(screen.getByLabelText("字幕")).toHaveValue("burned"));await waitFor(()=>expect(localStorage.getItem(`minicut:export-draft:${route}`)).toBeNull());
});
it("读取失败时允许重试，并能恢复页面刷新前未同步的配置",async()=>{
  const route="/offline-local-export";const draft={...api.defaultExportDraft(),options:{...api.defaultExportOptions(),subtitle_mode:"burned" as const},overrides:{a:{aspect_ratio:"1:1" as const,resolution:720 as const,fit:"pad" as const}}};
  localStorage.setItem(`minicut:export-draft:${route}`,JSON.stringify(draft));vi.mocked(api.getExportDraft).mockRejectedValueOnce(new Error("离线"));vi.mocked(api.saveExportDraft).mockRejectedValueOnce(new Error("离线"));
  render(<Harness route={route}/>);await screen.findByText("重试保存导出设置");expect(screen.getByLabelText("字幕")).toHaveValue("burned");expect(screen.getByLabelText("配置")).toHaveTextContent('"aspect_ratio":"1:1"');
  fireEvent.click(screen.getByText("重试保存导出设置"));await waitFor(()=>expect(localStorage.getItem(`minicut:export-draft:${route}`)).toBeNull());
});
it("切换作品期间不开放旧配置，晚到的读取不会覆盖新作品",async()=>{
  const late=deferred<api.ExportDraftResponse>();vi.mocked(api.getExportDraft).mockImplementationOnce(()=>late.promise).mockResolvedValueOnce({source:"saved",draft:{...api.defaultExportDraft(),options:{...api.defaultExportOptions(),aspect_ratio:"9:16"}}});
  const view=render(<Harness route="/old-output"/>);view.rerender(<Harness route="/new-output"/>);await waitFor(()=>expect(screen.getByLabelText("配置")).toHaveTextContent('"aspect_ratio":"9:16"'));
  late.resolve({source:"saved",draft:api.defaultExportDraft()});await waitFor(()=>expect(screen.getByLabelText("字幕")).toBeEnabled());expect(screen.getByLabelText("配置")).toHaveTextContent('"aspect_ratio":"9:16"');
});
it("没有本机副本时读取失败，重试后才开放编辑",async()=>{
  vi.mocked(api.getExportDraft).mockRejectedValueOnce(new Error("读取失败"));render(<Harness route="/retry-read"/>);await screen.findByText("重试读取导出设置");expect(screen.getByLabelText("字幕")).toBeDisabled();fireEvent.click(screen.getByText("重试读取导出设置"));await waitFor(()=>expect(screen.getByLabelText("字幕")).toBeEnabled());
});
