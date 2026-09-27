import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createGenerationPreset, deleteGenerationPreset, listGenerationPresets, renameGenerationPreset, updateGenerationPreset, type GenerationPreset } from "./api";
import { defaultGenerationDraft, type GenerationDraft } from "./generationDraft";
import { HighlightForm, type HighlightBrief } from "./HighlightForm";
import { PresetControls } from "./PresetControls";
import { usePresetLibrary } from "./usePresetLibrary";

vi.mock("./api",()=>({createGenerationPreset:vi.fn(),deleteGenerationPreset:vi.fn(),listGenerationPresets:vi.fn(),renameGenerationPreset:vi.fn(),updateGenerationPreset:vi.fn()}));
const template:GenerationPreset={preset_id:"interview",name:"双语访谈",created_at:"2026-09-27T01:00:00Z",updated_at:"2026-09-27T01:00:00Z",draft:{...defaultGenerationDraft(),preset:"knowledge_digest",prompts:{knowledge_digest:"原始自定义提示词"},instructions:"完整背景与限定",count:2,min_seconds:30,max_seconds:75,hook_enabled:true,hook_seconds:12.5,body_mode:"compact",translation_enabled:true,translation_language:"en",subtitle_mode:"translated"}};
function Harness({initial=defaultGenerationDraft(),submit=vi.fn(),changed=vi.fn()}:{initial?:GenerationDraft;submit?:(brief:HighlightBrief)=>void;changed?:(draft:GenerationDraft)=>void}) {
  const [draft,setDraft]=useState(initial);
  const library=usePresetLibrary();
  const current=library.presets.find(item=>item.preset_id===draft.custom_preset_id);
  function change(next:GenerationDraft) {setDraft(next);changed(next);}
  return <HighlightForm draft={draft} onChange={change} ready busy={library.busy}
    presetControls={<PresetControls draft={draft} onChange={change} library={library} disabled={false} />}
    presetDefaultPrompt={current?.draft.prompts[current.draft.preset]??null} onSubmit={submit} />;
}
beforeEach(()=>{
  vi.clearAllMocks();
  vi.mocked(listGenerationPresets).mockResolvedValue([structuredClone(template)]);
  vi.mocked(createGenerationPreset).mockImplementation(async(name,draft)=>({...template,preset_id:"new",name,draft:structuredClone(draft)}));
  vi.mocked(updateGenerationPreset).mockImplementation(async(id,name,draft)=>({...template,preset_id:id,name,draft:structuredClone(draft)}));
  vi.mocked(renameGenerationPreset).mockImplementation(async(id,name)=>({...template,preset_id:id,name}));
  vi.mocked(deleteGenerationPreset).mockResolvedValue({deleted:true});
});

it("应用完整工作流程填入全部参数，切回内置预设保留其原草稿",async()=>{
  const submit=vi.fn();
  const initial={...defaultGenerationDraft(),prompts:{...defaultGenerationDraft().prompts,knowledge_digest:"内置知识预设的草稿"}};
  const original=JSON.stringify(template);
  render(<Harness initial={initial} submit={submit} />);
  await screen.findByRole("option",{name:"双语访谈"});
  expect(screen.getAllByRole("combobox")[0]).toBe(screen.getByLabelText("预设"));
  expect(screen.queryByRole("group",{name:"应用内容"})).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("预设"),"custom:interview");
  expect(screen.getByLabelText("剪辑要求")).toHaveValue(initial.instructions);
  expect(screen.getByLabelText("数量")).toHaveValue(initial.count);
  expect(submit).not.toHaveBeenCalled();
  expect(screen.queryByRole("button",{name:"重新应用所选预设"})).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"用当前配置更新预设"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"全部参数"}));
  expect(screen.getByLabelText("预设提示词")).toHaveValue("原始自定义提示词");
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("完整背景与限定");
  expect(screen.getByLabelText("数量")).toHaveValue(2);
  expect(screen.getByLabelText("最短秒数")).toHaveValue(30);
  expect(screen.getByLabelText("最长秒数")).toHaveValue(75);
  expect(screen.getByLabelText("开场预告目标秒数")).toHaveValue(12.5);
  expect(screen.getByLabelText("正文模式")).toHaveValue("compact");
  expect(screen.getByLabelText("翻译为")).toHaveValue("en");
  expect(screen.getByLabelText("字幕显示")).toHaveValue("translated");
  expect(submit).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({preset:"knowledge_digest",preset_prompt:"原始自定义提示词",instructions:"完整背景与限定",count:2,min_ms:30000,max_ms:75000,hook_ms:12500,custom_preset_id:"interview",custom_preset_name:"双语访谈"}));
  await userEvent.clear(screen.getByLabelText("预设提示词"));
  await userEvent.type(screen.getByLabelText("预设提示词"),"仅改本次草稿");
  expect(updateGenerationPreset).not.toHaveBeenCalled();
  expect(JSON.stringify(template)).toBe(original);
  await userEvent.selectOptions(screen.getByLabelText("预设"),"knowledge_digest");
  expect(screen.getByLabelText("预设提示词")).toHaveValue("内置知识预设的草稿");
  expect(screen.queryByRole("group",{name:"应用内容"})).not.toBeInTheDocument();
});

it("仅应用提示词保留当前基础预设、时长、开场预告和翻译参数",async()=>{
  const changed=vi.fn();
  const initial={...defaultGenerationDraft(),count:4,min_seconds:10,max_seconds:20};
  vi.mocked(listGenerationPresets).mockResolvedValue([{...template,draft:{...template.draft,preset:"clean_speech",prompts:{clean_speech:"口播提示词"}}}]);
  render(<Harness initial={initial} changed={changed} />);
  await screen.findByRole("option",{name:"双语访谈"});
  await userEvent.selectOptions(screen.getByLabelText("预设"),"custom:interview");
  expect(changed).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button",{name:"仅提示词"}));
  expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({preset:"podcast_highlights",count:4,min_seconds:10,max_seconds:20,hook_enabled:false,translation_enabled:false,body_mode:"continuous",custom_prompt:"口播提示词",instructions:"完整背景与限定"}));
  expect(screen.getByLabelText("最短秒数")).toBeEnabled();
  expect(screen.getByLabelText("原话开场预告")).not.toBeChecked();
  expect(screen.getByLabelText("翻译字幕")).not.toBeChecked();
});

it("另存并在另一个项目界面使用新预设，保存名称及配置",async()=>{
  const first=render(<Harness initial={{...defaultGenerationDraft(),instructions:"项目 A 的流程"}} />);
  await screen.findByRole("option",{name:"双语访谈"});
  await userEvent.click(screen.getByText("管理我的预设"));
  await userEvent.type(screen.getByLabelText("预设名称"),"新工作流程");
  await userEvent.click(screen.getByRole("button",{name:"另存为预设"}));
  await screen.findByText("已保存“新工作流程”，所有项目均可使用");
  expect(createGenerationPreset).toHaveBeenCalledWith("新工作流程",expect.objectContaining({instructions:"项目 A 的流程"}));
  expect(screen.getByLabelText("预设")).toHaveValue("custom:new");
  const created=await vi.mocked(createGenerationPreset).mock.results[0].value as GenerationPreset;
  first.unmount();
  vi.mocked(listGenerationPresets).mockResolvedValue([created]);
  render(<Harness initial={{...defaultGenerationDraft(),instructions:"项目 B 独立草稿"}} />);
  await screen.findByRole("option",{name:"新工作流程"});
  await userEvent.selectOptions(screen.getByLabelText("预设"),"custom:new");
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("项目 B 独立草稿");
  await userEvent.click(screen.getByRole("button",{name:"全部参数"}));
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("项目 A 的流程");
});

it("重命名只改名字，明确更新才保存当前配置，删除后草稿仍可生成",async()=>{
  const submit=vi.fn();
  render(<Harness submit={submit} />);
  await screen.findByRole("option",{name:"双语访谈"});
  await userEvent.selectOptions(screen.getByLabelText("预设"),"custom:interview");
  await userEvent.click(screen.getByRole("button",{name:"全部参数"}));
  await userEvent.click(screen.getByText("管理我的预设"));
  fireEvent.change(screen.getByLabelText("预设提示词"),{target:{value:"修改后的提示词"}});
  fireEvent.change(screen.getByLabelText("数量"),{target:{value:"4"}});
  fireEvent.change(screen.getByLabelText("预设名称"),{target:{value:"新名称"}});
  await userEvent.click(screen.getByRole("button",{name:"重命名预设"}));
  await screen.findByText("已重命名为“新名称”");
  expect(renameGenerationPreset).toHaveBeenCalledWith("interview","新名称");
  expect(updateGenerationPreset).not.toHaveBeenCalled();
  expect(screen.getByLabelText("预设提示词")).toHaveValue("修改后的提示词");
  await userEvent.click(screen.getByRole("button",{name:"用当前配置更新预设"}));
  await screen.findByText("已用当前提示词和参数更新“新名称”");
  expect(updateGenerationPreset).toHaveBeenCalledWith("interview","新名称",expect.objectContaining({custom_prompt:"修改后的提示词",count:4}));
  await userEvent.click(screen.getByRole("button",{name:/^删除预设$/}));
  expect(deleteGenerationPreset).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button",{name:"确认删除预设"}));
  await screen.findByText("已删除“新名称”；当前草稿和历史配置仍保留");
  expect(screen.getByLabelText("预设提示词")).toHaveValue("修改后的提示词");
  expect(screen.getByRole("button",{name:"用当前配置更新预设"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({preset_prompt:"修改后的提示词",count:4,custom_preset_name:"新名称"}));
});

it("预设库读取或保存失败可重试，已有自定义草稿不被清空",async()=>{
  vi.mocked(listGenerationPresets).mockRejectedValueOnce(new Error("无法连接预设库"));
  const initial={...defaultGenerationDraft(),custom_preset_id:"interview",custom_preset_name:"双语访谈",custom_prompt:"已保存的项目文字"};
  render(<Harness initial={initial} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("无法连接预设库");
  expect(screen.getByLabelText("预设提示词")).toHaveValue("已保存的项目文字");
  expect(screen.getByRole("button",{name:"生成候选"})).toBeEnabled();
  await userEvent.click(screen.getByRole("button",{name:"重试读取预设库"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"仅提示词"})).toBeEnabled());
  await userEvent.click(screen.getByText("管理我的预设"));
  vi.mocked(updateGenerationPreset).mockRejectedValueOnce(new Error("磁盘暂不可写"));
  await userEvent.click(screen.getByRole("button",{name:"用当前配置更新预设"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("磁盘暂不可写");
  expect(screen.getByLabelText("预设提示词")).toHaveValue("已保存的项目文字");
  await userEvent.click(screen.getByRole("button",{name:"用当前配置更新预设"}));
  await screen.findByText("已用当前提示词和参数更新“双语访谈”");
});

it("不完整的工作流程不能误存为模板，说明需要修正的参数",async()=>{
  render(<Harness initial={{...defaultGenerationDraft(),count:0}} />);
  await screen.findByRole("option",{name:"双语访谈"});
  await userEvent.click(screen.getByText("管理我的预设"));
  fireEvent.change(screen.getByLabelText("预设名称"),{target:{value:"待整理"}});
  await userEvent.click(screen.getByRole("button",{name:"另存为预设"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("数量（1–10）");
  expect(createGenerationPreset).not.toHaveBeenCalled();
});

it("在预设名称中按回车不会误触发 AI 生成",async()=>{
  const submit=vi.fn();
  render(<Harness submit={submit} />);
  await screen.findByRole("option",{name:"双语访谈"});
  await userEvent.click(screen.getByText("管理我的预设"));
  await userEvent.type(screen.getByLabelText("预设名称"),"新名称{Enter}");
  expect(submit).not.toHaveBeenCalled();
  expect(createGenerationPreset).not.toHaveBeenCalled();
});
