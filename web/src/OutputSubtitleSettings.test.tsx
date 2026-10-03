import { beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { defaultSubtitleStyle, listSubtitleFonts, readHighlightTask, saveOutputSubtitleSettings, startOutputTranslation, type HighlightOutput, type HighlightResult } from "./api";
import { OutputSubtitleSettings } from "./OutputSubtitleSettings";

vi.mock("./api", async original => ({
  ...await original<typeof import("./api")>(),
  listSubtitleFonts:vi.fn(),
  readHighlightTask:vi.fn(),
  saveOutputSubtitleSettings:vi.fn(),
  startOutputTranslation:vi.fn(),
}));

const plan:HighlightOutput={output_id:"video",title:"Title",reason:"Reason",revision:3,duration_ms:2000,clips:[{instance_id:"one",segment_id:"s",role:"body",text:"Hello",start_ms:0,end_ms:2000}]};
const result={collection_id:"collection",asset_id:"asset",notes:[],brief:{} as HighlightResult["brief"],outputs:[{...plan,revision:4}]} as HighlightResult;

beforeEach(()=>{window.localStorage.clear();vi.clearAllMocks();vi.mocked(listSubtitleFonts).mockResolvedValue([{id:"heiti",name:"黑体"},{id:"songti",name:"宋体"}]);});

it("作品级设置保存显示模式、字号、位置和上下顺序",async()=>{
  vi.mocked(saveOutputSubtitleSettings).mockResolvedValue(result);
  const updated=vi.fn();
  render(<OutputSubtitleSettings project="project" collection="collection" plan={plan} disabled={false} onUpdated={updated} />);
  await userEvent.selectOptions(screen.getByLabelText("全局字幕显示"),"translated");
  await userEvent.selectOptions(screen.getByLabelText("双语上下顺序"),"translation_first");
  await userEvent.clear(screen.getByLabelText("原文字号"));
  await userEvent.type(screen.getByLabelText("原文字号"),"72");
  await userEvent.click(screen.getByRole("button",{name:"保存字幕设置"}));
  await waitFor(()=>expect(saveOutputSubtitleSettings).toHaveBeenCalledWith("project","collection","video",3,expect.objectContaining({subtitle_mode:"translated",subtitle_style:expect.objectContaining({source_size:72}),subtitle_order:"translation_first"})));
  expect(updated).toHaveBeenCalledWith(result);
});

it("已有译文的作品可切换为仅原文",async()=>{
  vi.mocked(saveOutputSubtitleSettings).mockResolvedValue(result);
  render(<OutputSubtitleSettings project="project" collection="collection" plan={{...plan,clips:[{...plan.clips[0],translation_text:"你好",translation_language:"zh"}]}} disabled={false} onUpdated={vi.fn()} />);
  await userEvent.selectOptions(screen.getByLabelText("全局字幕显示"),"source");
  await userEvent.click(screen.getByRole("button",{name:"保存字幕设置"}));
  await waitFor(()=>expect(saveOutputSubtitleSettings).toHaveBeenCalledWith("project","collection","video",3,expect.objectContaining({subtitle_mode:"source"})));
});

it("翻译按钮明确触发当前作品任务并接收结果",async()=>{
  vi.mocked(startOutputTranslation).mockResolvedValue({task_id:"translation-task",status:"pending",result:null,error:null});
  vi.mocked(readHighlightTask).mockResolvedValue({task_id:"translation-task",status:"succeeded",result,error:null});
  const updated=vi.fn();
  render(<OutputSubtitleSettings project="project" collection="collection" plan={plan} disabled={false} onUpdated={updated} />);
  await userEvent.click(screen.getByRole("button",{name:"翻译字幕"}));
  await waitFor(()=>expect(startOutputTranslation).toHaveBeenCalledWith("project","collection","video",3,"zh"));
  await waitFor(()=>expect(updated).toHaveBeenCalledWith(result));
  expect(window.localStorage.getItem("minicut-translation:project:collection:video")).toBeNull();
});

it("翻译提交期间锁定控件，重复点击不会提交第二个任务，失败后可重试",async()=>{
  let rejectRequest!:(reason:Error)=>void;
  vi.mocked(startOutputTranslation).mockImplementationOnce(()=>new Promise((_,reject)=>{rejectRequest=reject;}));
  render(<OutputSubtitleSettings project="project" collection="collection" plan={plan} disabled={false} onUpdated={vi.fn()} />);
  const user=userEvent.setup();
  await user.dblClick(screen.getByRole("button",{name:"翻译字幕"}));
  expect(startOutputTranslation).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button",{name:"正在提交…"})).toBeDisabled();
  expect(screen.getByLabelText("翻译语言")).toBeDisabled();
  expect(screen.getByLabelText("原文字号")).toBeDisabled();
  await act(async()=>rejectRequest(new Error("服务暂时不可用")));
  expect(await screen.findByRole("alert")).toHaveTextContent("服务暂时不可用");
  expect(screen.getByRole("button",{name:"翻译字幕"})).toBeEnabled();
  expect(screen.getByLabelText("翻译语言")).toBeEnabled();
  vi.mocked(startOutputTranslation).mockResolvedValueOnce({task_id:"retry",status:"pending",result:null,error:null});
  vi.mocked(readHighlightTask).mockResolvedValue({task_id:"retry",status:"pending",result:null,error:null});
  await user.click(screen.getByRole("button",{name:"翻译字幕"}));
  expect(startOutputTranslation).toHaveBeenCalledTimes(2);
  expect(await screen.findByRole("button",{name:"正在翻译…"})).toBeDisabled();
});

it("放弃字幕设置恢复保存值和翻译入口，不调用保存或模型",async()=>{
  const dirty=vi.fn();
  render(<OutputSubtitleSettings project="project" collection="collection" plan={plan} disabled={false} onUpdated={vi.fn()} onDirty={dirty} />);
  await userEvent.selectOptions(screen.getByLabelText("双语上下顺序"),"translation_first");
  expect(screen.getByRole("button",{name:"翻译字幕"})).toBeDisabled();
  expect(screen.getByText("设置未保存，保存或放弃后可翻译。")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"放弃设置"}));
  expect(screen.getByLabelText("双语上下顺序")).toHaveValue("source_first");
  expect(screen.getByRole("button",{name:"翻译字幕"})).toBeEnabled();
  expect(dirty).toHaveBeenLastCalledWith(false);
  expect(saveOutputSubtitleSettings).not.toHaveBeenCalled();
  expect(startOutputTranslation).not.toHaveBeenCalled();
});

it("超出范围的字号显示错误并禁止保存",async()=>{
  render(<OutputSubtitleSettings project="project" collection="collection" plan={plan} disabled={false} onUpdated={vi.fn()} />);
  await userEvent.clear(screen.getByLabelText("原文字号"));
  await userEvent.type(screen.getByLabelText("原文字号"),"2");
  expect(screen.getByRole("alert")).toHaveTextContent("16–200");
  expect(screen.getByRole("button",{name:"保存字幕设置"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"放弃设置"}));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("已有全部译文时说明禁用原因，历史只读时提供对应提示",()=>{
  const props={project:"project",collection:"collection",plan:{...plan,clips:[{...plan.clips[0],translation_text:"你好",translation_language:"zh" as const}]},disabled:false,onUpdated:vi.fn()};
  const view=render(<OutputSubtitleSettings {...props}/>);
  expect(screen.getByRole("button",{name:"翻译字幕"})).toHaveAccessibleDescription("字幕已全部翻译。");
  expect(screen.getByRole("button",{name:"翻译字幕"})).toBeDisabled();
  view.rerender(<OutputSubtitleSettings {...props} disabled disabledReason="历史版本只读，请切回当前版本后修改或翻译。"/>);
  expect(screen.getByRole("button",{name:"翻译字幕"})).toHaveAccessibleDescription("历史版本只读，请切回当前版本后修改或翻译。");
});


it("保存原文译文不同字体、共用效果，重新打开独立恢复",async()=>{
  const updated=vi.fn();
  vi.mocked(saveOutputSubtitleSettings).mockResolvedValue(result);
  const view=render(<OutputSubtitleSettings project="p" collection="c" plan={plan} disabled={false} onUpdated={updated}/>);
  await waitFor(()=>expect(screen.getByLabelText("原文字体")).toBeEnabled());
  await userEvent.selectOptions(screen.getByLabelText("原文字体"),"songti");
  await userEvent.selectOptions(screen.getByLabelText("译文字体"),"heiti");
  fireEvent.change(screen.getByLabelText("译文字号"),{target:{value:"56"}});
  fireEvent.change(screen.getByLabelText("字幕文字颜色"),{target:{value:"#ffff00"}});
  fireEvent.change(screen.getByLabelText("字幕描边宽度"),{target:{value:"6"}});
  fireEvent.change(screen.getByLabelText("字幕阴影强度"),{target:{value:"3"}});
  await userEvent.click(screen.getByLabelText("字幕加粗"));
  await userEvent.click(screen.getByLabelText("字幕背景框"));
  fireEvent.change(screen.getByLabelText("字幕背景不透明度"),{target:{value:"65"}});
  expect(screen.getByRole("button",{name:"翻译字幕"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"保存字幕设置"}));
  const saved={...defaultSubtitleStyle(),source_font_id:"songti",translation_font_id:"heiti",translation_size:56,text_color:"#ffff00",stroke_width:6,shadow_width:3,bold:false,background_enabled:true,background_opacity:65};
  expect(saveOutputSubtitleSettings).toHaveBeenCalledWith("p","c","video",3,expect.objectContaining({subtitle_style:saved}));
  view.unmount();
  render(<OutputSubtitleSettings project="p" collection="c" plan={{...plan,revision:4,subtitle_style:saved}} disabled={false} onUpdated={updated}/>);
  expect(screen.getByLabelText("原文字体")).toHaveValue("songti");
  expect(screen.getByLabelText("译文字体")).toHaveValue("heiti");
  expect(screen.getByLabelText("译文字号")).toHaveValue(56);
  expect(screen.getByLabelText("字幕背景不透明度")).toHaveValue(65);
  expect(screen.getByLabelText("字幕加粗")).not.toBeChecked();
  expect(screen.getByRole("button",{name:"保存字幕设置"})).toBeDisabled();
});

it("已选字体缺失时提示重选，字体读取失败可重试",async()=>{
  vi.mocked(listSubtitleFonts).mockRejectedValueOnce(new Error("字体读取失败"));
  render(<OutputSubtitleSettings project="p" collection="c" plan={{...plan,subtitle_style:{...defaultSubtitleStyle(),translation_font_id:"missing"}}} disabled={false} onUpdated={vi.fn()}/>);
  expect(await screen.findByText("字体读取失败")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"重试读取字体"}));
  expect(await screen.findByText("译文字体在本机不可用，请重新选择。")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("原文字号"),{target:{value:"80"}});
  expect(screen.getByRole("button",{name:"保存字幕设置"})).toBeDisabled();
  await userEvent.selectOptions(screen.getByLabelText("译文字体"),"heiti");
  expect(screen.getByLabelText("原文字体")).toHaveValue("");
  expect(screen.getByRole("button",{name:"保存字幕设置"})).toBeEnabled();
});

it("放弃设置恢复所有效果；清空、非整数和越界输入不能保存",async()=>{
  render(<OutputSubtitleSettings project="p" collection="c" plan={{...plan,subtitle_style:defaultSubtitleStyle()}} disabled={false} onUpdated={vi.fn()}/>);
  for(const value of ["", "48.5", "201"]){
    fireEvent.change(screen.getByLabelText("原文字号"),{target:{value}});
    expect(screen.getByRole("button",{name:"保存字幕设置"})).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("16–200");
  }
  await userEvent.click(screen.getByRole("button",{name:"放弃设置"}));
  await userEvent.click(screen.getByLabelText("字幕背景框"));
  fireEvent.change(screen.getByLabelText("字幕背景不透明度"),{target:{value:"101"}});
  expect(screen.getByRole("button",{name:"保存字幕设置"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"放弃设置"}));
  expect(screen.getByLabelText("原文字号")).toHaveValue(64);
  expect(screen.getByLabelText("字幕背景框")).not.toBeChecked();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
