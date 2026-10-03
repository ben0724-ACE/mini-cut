import {useState} from "react";
import {beforeEach,expect,it,vi} from "vitest";
import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {ExportPresetControls} from "./ExportPresetControls";
import * as api from "./exportSettingsApi";
vi.mock("./exportSettingsApi",async original=>({...await original<typeof import("./exportSettingsApi")>(),listExportPresets:vi.fn(),writeExportPreset:vi.fn(),renameExportPreset:vi.fn(),deleteExportPreset:vi.fn()}));
const preset:api.ExportPreset={preset_id:"export-one",name:"竖屏烧录",options:{...api.defaultExportOptions(),aspect_ratio:"9:16",subtitle_mode:"burned",crop_left:10},created_at:"now",updated_at:"now"};
let presets:api.ExportPreset[]=[];
function Harness(){const [draft,setDraft]=useState<api.ExportDraft>({...api.defaultExportDraft(),overrides:{a:{aspect_ratio:"1:1" as const,resolution:720 as const,fit:"pad" as const}}});return <><ExportPresetControls draft={draft} onChange={setDraft} batch/><output aria-label="配置">{JSON.stringify(draft)}</output><button onClick={()=>setDraft({...draft,options:{...draft.options,resolution:720}})}>调整当前分辨率</button></>;}
beforeEach(()=>{vi.clearAllMocks();presets=[structuredClone(preset)];vi.mocked(api.listExportPresets).mockImplementation(async()=>structuredClone(presets));vi.mocked(api.writeExportPreset).mockImplementation(async(name,options,id)=>{const saved={...preset,preset_id:id??"new",name,options};presets=[...presets.filter(item=>item.preset_id!==saved.preset_id),saved];return saved;});vi.mocked(api.renameExportPreset).mockImplementation(async(id,name)=>{const saved={...preset,preset_id:id,name};presets=presets.map(item=>item.preset_id===id?saved:item);return saved;});vi.mocked(api.deleteExportPreset).mockImplementation(async id=>{presets=presets.filter(item=>item.preset_id!==id);return {};});});
it("选择不应用，应用保留逐条覆盖，微调不修改预设，显式更新才写库",async()=>{
  render(<Harness/>);await screen.findByRole("option",{name:preset.name});fireEvent.change(screen.getByLabelText("导出预设"),{target:{value:preset.preset_id}});expect(screen.getByLabelText("配置")).toHaveTextContent('"aspect_ratio":"original"');expect(screen.getByText("更新预设")).toBeDisabled();
  fireEvent.click(screen.getByText("应用预设"));expect(screen.getByLabelText("配置")).toHaveTextContent('"aspect_ratio":"9:16"');expect(screen.getByLabelText("配置")).toHaveTextContent('"overrides":{"a":{"aspect_ratio":"1:1"');
  fireEvent.click(screen.getByText("调整当前分辨率"));expect(api.writeExportPreset).not.toHaveBeenCalled();fireEvent.click(screen.getByText("更新预设"));await waitFor(()=>expect(api.writeExportPreset).toHaveBeenCalledWith(preset.name,expect.objectContaining({resolution:720,subtitle_mode:"burned",crop_left:10}),preset.preset_id));
});
it("另存、重命名、删除后保留设置，恢复默认仍保留逐条覆盖",async()=>{
  const user=userEvent.setup();render(<Harness/>);await screen.findByRole("option",{name:preset.name});await user.click(screen.getByText("管理预设"));await user.type(screen.getByLabelText("导出预设名称"),"新预设");await user.click(screen.getByText("另存为预设"));await screen.findByRole("option",{name:"新预设"});
  await user.clear(screen.getByLabelText("导出预设名称"));await user.type(screen.getByLabelText("导出预设名称"),"改名");await user.click(screen.getByText("重命名预设"));await screen.findByRole("option",{name:"改名"});await user.click(screen.getByText("删除预设"));await user.click(screen.getByText("确认删除预设"));await waitFor(()=>expect(api.deleteExportPreset).toHaveBeenCalledWith("new"));expect(screen.getByLabelText("配置")).toHaveTextContent('"overrides":{"a"');
  await user.click(screen.getByText("恢复默认"));expect(screen.getByLabelText("配置")).toHaveTextContent('"subtitle_mode":"soft"');expect(screen.getByLabelText("配置")).toHaveTextContent('"preset_id":null');expect(screen.getByLabelText("配置")).toHaveTextContent('"overrides":{"a"');
});
it("原预设已删除仍保留当前配置，库读取失败可重试",async()=>{
  vi.mocked(api.listExportPresets).mockRejectedValueOnce(new Error("库不可用"));render(<ExportPresetControls draft={{...api.defaultExportDraft(),preset_id:"missing",preset_name:"旧预设"}} onChange={vi.fn()}/>);await screen.findByText("重试");fireEvent.click(screen.getByText("重试"));await screen.findByText("原预设已删除或未找到，当前设置仍然保留。");expect(screen.getByText("更新预设")).toBeDisabled();
});

it("完整预设保存原文译文字体及全部效果，应用等待作品保存成功",async()=>{
  const {defaultSubtitleSettings}=await import("./SubtitleAppearanceControls");
  const layout=defaultSubtitleSettings();layout.subtitle_style={...layout.subtitle_style!,source_font_id:"heiti",translation_font_id:"songti",source_size:90,translation_size:60,text_color:"#ffcc00",stroke_width:6,shadow_width:3,background_enabled:true,background_opacity:65};
  presets=[{...preset,options:{...preset.options,subtitle_settings:layout}}];
  const apply=vi.fn().mockResolvedValue(undefined);const change=vi.fn();
  render(<ExportPresetControls draft={api.defaultExportDraft()} onChange={change} onApply={apply} saveOptions={{...api.defaultExportOptions(),subtitle_settings:layout}}/>);
  await screen.findByRole("option",{name:preset.name});fireEvent.change(screen.getByLabelText("导出预设"),{target:{value:preset.preset_id}});fireEvent.click(screen.getByText("应用预设"));
  await waitFor(()=>expect(apply).toHaveBeenCalledWith(expect.objectContaining({options:expect.objectContaining({subtitle_settings:layout})})));
  expect(change).not.toHaveBeenCalled();await screen.findByText(/已应用.*包含完整字幕设置/);
  fireEvent.change(screen.getByLabelText("导出预设名称"),{target:{value:"完整字幕"}});fireEvent.click(screen.getByText("另存为预设"));
  await waitFor(()=>expect(api.writeExportPreset).toHaveBeenCalledWith("完整字幕",expect.objectContaining({subtitle_settings:layout})));
});
it("旧预设保留当前批量字幕样式，应用失败不显示成功",async()=>{
  const {defaultSubtitleSettings}=await import("./SubtitleAppearanceControls");const layout=defaultSubtitleSettings();const change=vi.fn();
  const view=render(<ExportPresetControls draft={{...api.defaultExportDraft(),options:{...api.defaultExportOptions(),subtitle_settings:layout}}} onChange={change} batch/>);
  await screen.findByRole("option",{name:preset.name});fireEvent.change(screen.getByLabelText("导出预设"),{target:{value:preset.preset_id}});fireEvent.click(screen.getByText("应用预设"));
  expect(change).toHaveBeenCalledWith(expect.objectContaining({options:expect.objectContaining({subtitle_settings:layout})}));
  view.unmount();render(<ExportPresetControls draft={api.defaultExportDraft()} onChange={vi.fn()} onApply={vi.fn().mockRejectedValue(new Error("作品版本冲突"))}/>);
  await screen.findByRole("option",{name:preset.name});fireEvent.change(screen.getByLabelText("导出预设"),{target:{value:preset.preset_id}});fireEvent.click(screen.getByText("应用预设"));
  await screen.findByText("作品版本冲突");expect(screen.queryByText(/已应用/)).not.toBeInTheDocument();
});
