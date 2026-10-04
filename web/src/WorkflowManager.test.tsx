import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {render,screen,waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {WorkflowManager} from "./WorkflowManager";
import {defaultGenerationDraft} from "./generationDraft";
import {defaultExportOptions} from "./exportSettingsApi";
import * as api from "./api";
import * as exportApi from "./exportSettingsApi";
import * as coverApi from "./coverApi";
import * as workflowApi from "./workflowApi";
vi.mock("./api",async original=>({...await original<typeof import("./api")>(),listGenerationPresets:vi.fn(),getGenerationDraft:vi.fn(),recoverTranscription:vi.fn(),recoverHighlights:vi.fn()}));
vi.mock("./exportSettingsApi",async original=>({...await original<typeof import("./exportSettingsApi")>(),listExportPresets:vi.fn()}));
vi.mock("./coverApi",async original=>({...await original<typeof import("./coverApi")>(),listCoverTemplates:vi.fn()}));
vi.mock("./workflowApi",async original=>({...await original<typeof import("./workflowApi")>(),listWorkflows:vi.fn(),writeWorkflow:vi.fn()}));
beforeEach(()=>{vi.clearAllMocks();vi.mocked(workflowApi.listWorkflows).mockResolvedValue([]);vi.mocked(api.listGenerationPresets).mockResolvedValue([{preset_id:"g",name:"AI 访谈",draft:{...defaultGenerationDraft(),count:5},created_at:"",updated_at:""}]);vi.mocked(exportApi.listExportPresets).mockResolvedValue([{preset_id:"e",name:"竖屏",options:{...defaultExportOptions(),aspect_ratio:"9:16"},created_at:"",updated_at:""}]);vi.mocked(coverApi.listCoverTemplates).mockResolvedValue([]);});
afterEach(()=>localStorage.clear());
it("按需读取预设，将生成和导出预设组合成独立工作流",async()=>{
  const user=userEvent.setup();const saved=vi.fn();render(<WorkflowManager project="p" onSaved={saved}/>);expect(api.listGenerationPresets).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button",{name:"管理我的工作流"}));await waitFor(()=>expect(screen.getByLabelText("工作流名称")).toBeEnabled());await user.type(screen.getByLabelText("工作流名称"),"AI 博主");
  await user.selectOptions(screen.getByLabelText("工作流生成预设"),"g");await user.selectOptions(screen.getByLabelText("工作流导出预设"),"e");await user.selectOptions(screen.getByLabelText("工作流完成方式"),"export");
  vi.mocked(workflowApi.writeWorkflow).mockImplementation(async body=>({...body,workflow_id:"w",created_at:"",updated_at:""}));await user.click(screen.getByRole("button",{name:"另存为工作流"}));
  await waitFor(()=>expect(saved).toHaveBeenCalled());const body=vi.mocked(workflowApi.writeWorkflow).mock.calls[0][0];expect(body.generation.count).toBe(5);expect(body.export_options.aspect_ratio).toBe("9:16");expect(body.auto_export).toBe(true);
});
it("可以载入当前素材已保存的配置，不触发生成",async()=>{
  vi.mocked(api.getGenerationDraft).mockResolvedValue({source:"asset",draft:{...defaultGenerationDraft(),count:7}});vi.mocked(api.recoverTranscription).mockResolvedValue(null);vi.mocked(api.recoverHighlights).mockResolvedValue(null);const user=userEvent.setup();render(<WorkflowManager project="p" asset="a"/>);
  await user.click(screen.getByRole("button",{name:"管理我的工作流"}));await waitFor(()=>expect(screen.getByLabelText("工作流名称")).toBeEnabled());await user.click(screen.getByRole("button",{name:"载入当前素材已保存配置"}));
  expect(await screen.findByText(/当前配置：7 条作品/)).toBeInTheDocument();expect(api.getGenerationDraft).toHaveBeenCalledWith("p","a");
});
it("弹窗关闭后恢复焦点，重新打开保留尚未保存的工作流名称",async()=>{
  const user=userEvent.setup();render(<WorkflowManager project="p"/>);
  const trigger=screen.getByRole("button",{name:"管理我的工作流"});
  await user.click(trigger);await waitFor(()=>expect(screen.getByLabelText("工作流名称")).toBeEnabled());
  await user.type(screen.getByLabelText("工作流名称"),"未保存的工作流");
  await user.keyboard("{Escape}");expect(screen.queryByRole("dialog")).not.toBeInTheDocument();expect(trigger).toHaveFocus();
  await user.click(trigger);expect(screen.getByRole("dialog",{name:"管理我的工作流"})).toBeInTheDocument();
  expect(screen.getByLabelText("工作流名称")).toHaveValue("未保存的工作流");expect(api.listGenerationPresets).toHaveBeenCalledTimes(1);
});

it("工作流导出预设带入原文译文字体和共用效果",async()=>{
  const {defaultSubtitleSettings}=await import("./SubtitleAppearanceControls");const layout=defaultSubtitleSettings();layout.subtitle_style={...layout.subtitle_style!,source_font_id:"heiti",translation_font_id:"songti",background_enabled:true};
  vi.mocked(exportApi.listExportPresets).mockResolvedValue([{preset_id:"full",name:"完整成片",options:{...defaultExportOptions(),subtitle_settings:layout},created_at:"",updated_at:""}]);
  vi.mocked(workflowApi.writeWorkflow).mockImplementation(async body=>({...body,workflow_id:"w",created_at:"",updated_at:""}));const user=userEvent.setup();render(<WorkflowManager project="p"/>);
  await user.click(screen.getByRole("button",{name:"管理我的工作流"}));await waitFor(()=>expect(screen.getByLabelText("工作流名称")).toBeEnabled());await user.type(screen.getByLabelText("工作流名称"),"完整样式");await user.selectOptions(screen.getByLabelText("工作流导出预设"),"full");await user.click(screen.getByText("另存为工作流"));
  await waitFor(()=>expect(workflowApi.writeWorkflow).toHaveBeenCalledWith(expect.objectContaining({layout:expect.objectContaining(layout),export_options:expect.objectContaining({subtitle_settings:layout})}),undefined));
});
