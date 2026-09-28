import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readHighlightTask, saveOutputSubtitleSettings, startOutputTranslation, type HighlightOutput, type HighlightResult } from "./api";
import { OutputSubtitleSettings } from "./OutputSubtitleSettings";

vi.mock("./api", async original => ({
  ...await original<typeof import("./api")>(),
  readHighlightTask:vi.fn(),
  saveOutputSubtitleSettings:vi.fn(),
  startOutputTranslation:vi.fn(),
}));

const plan:HighlightOutput={output_id:"video",title:"Title",reason:"Reason",revision:3,duration_ms:2000,clips:[{instance_id:"one",segment_id:"s",role:"body",text:"Hello",start_ms:0,end_ms:2000}]};
const result={collection_id:"collection",asset_id:"asset",notes:[],brief:{} as HighlightResult["brief"],outputs:[{...plan,revision:4}]} as HighlightResult;

beforeEach(()=>{window.localStorage.clear();vi.clearAllMocks();});

it("作品级设置保存显示模式、字号、位置和上下顺序",async()=>{
  vi.mocked(saveOutputSubtitleSettings).mockResolvedValue(result);
  const updated=vi.fn();
  render(<OutputSubtitleSettings project="project" collection="collection" plan={plan} disabled={false} onUpdated={updated} />);
  await userEvent.selectOptions(screen.getByLabelText("全局字幕显示"),"translated");
  await userEvent.selectOptions(screen.getByLabelText("双语上下顺序"),"translation_first");
  await userEvent.clear(screen.getByLabelText("原文字号"));
  await userEvent.type(screen.getByLabelText("原文字号"),"1.2");
  await userEvent.click(screen.getByRole("button",{name:"保存字幕设置"}));
  await waitFor(()=>expect(saveOutputSubtitleSettings).toHaveBeenCalledWith("project","collection","video",3,expect.objectContaining({subtitle_mode:"translated",subtitle_source_scale:1.2,subtitle_order:"translation_first"})));
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
