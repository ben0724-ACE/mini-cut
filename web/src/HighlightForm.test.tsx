import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HighlightForm } from "./HighlightForm";

it("未转录不能生成，切换预设保留各自的提示词草稿", async () => {
  const view = render(<HighlightForm ready={false} busy={false} onSubmit={vi.fn()} />);
  expect(screen.getByRole("button", {name: "生成候选"})).toBeDisabled();
  await userEvent.clear(screen.getByLabelText("剪辑提示词"));
  await userEvent.type(screen.getByLabelText("剪辑提示词"), "保留反方论述");
  await userEvent.selectOptions(screen.getByLabelText("预设"), "opinion_first");
  await userEvent.selectOptions(screen.getByLabelText("预设"), "podcast_highlights");
  expect(screen.getByLabelText("剪辑提示词")).toHaveValue("保留反方论述");
  view.rerender(<HighlightForm ready busy={false} onSubmit={vi.fn()} />);
  expect(screen.getByRole("button", {name: "生成候选"})).toBeEnabled();
});
it("校验时长并传递自定义要求", async () => {
  const submit = vi.fn();
  render(<HighlightForm ready busy={false} onSubmit={submit} />);
  await userEvent.clear(screen.getByLabelText("最短秒数"));
  await userEvent.type(screen.getByLabelText("最短秒数"), "100");
  await userEvent.click(screen.getByRole("button", {name: "生成候选"}));
  expect(screen.getByRole("alert")).toHaveTextContent("时长");
  expect(submit).not.toHaveBeenCalled();
});

it("预设提示词可编辑，单条作品不受作品间重叠限制", async () => {
  const submit=vi.fn();
  render(<HighlightForm ready busy={false} onSubmit={submit} />);
  await userEvent.clear(screen.getByLabelText("剪辑提示词"));
  await userEvent.type(screen.getByLabelText("剪辑提示词"),"选择完整的幽默故事");
  await userEvent.clear(screen.getByLabelText("数量"));
  await userEvent.type(screen.getByLabelText("数量"),"1");
  expect(screen.getByLabelText("源内容重复上限")).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({editing_prompt:"选择完整的幽默故事",max_source_overlap:1,count:1}));
  const brief = submit.mock.calls[0][0];
  expect(brief).not.toHaveProperty("preset_prompt");
  expect(brief).not.toHaveProperty("instructions");
  expect(screen.queryByLabelText("剪辑要求")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("预设提示词")).not.toBeInTheDocument();
});

it("清理预设说明连续模式限制，观点预设不自动开启开场预告", async () => {
  const submit=vi.fn();
  render(<HighlightForm ready busy={false} onSubmit={submit} />);
  await userEvent.selectOptions(screen.getByLabelText("预设"), "clean_speech");
  expect(screen.getByText(/当前为连续正文/)).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("正文模式"), "compact");
  expect(screen.getByText(/当前为精简拼接/)).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("预设"), "opinion_first");
  await userEvent.click(screen.getByRole("button", {name:"生成候选"}));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({body_mode:"compact",hook_ms:null}));
});

it("自定义开场预告时长发送毫秒，关闭后不发送时长", async () => {
  const submit=vi.fn();
  render(<HighlightForm ready busy={false} onSubmit={submit} />);
  await userEvent.click(screen.getByLabelText("原话开场预告"));
  expect(screen.getByLabelText("开场预告目标秒数")).toHaveValue(5);
  await userEvent.clear(screen.getByLabelText("开场预告目标秒数"));
  await userEvent.type(screen.getByLabelText("开场预告目标秒数"), "12.5");
  await userEvent.click(screen.getByRole("button", {name:"生成候选"}));
  expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({hook_ms:12500}));
  await userEvent.click(screen.getByLabelText("原话开场预告"));
  await userEvent.click(screen.getByRole("button", {name:"生成候选"}));
  expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({hook_ms:null}));
});

it("字幕翻译可选目标语言和仅译文，关闭后不请求翻译",async()=>{
  const submit=vi.fn();
  render(<HighlightForm ready busy={false} onSubmit={submit} />);
  await userEvent.click(screen.getByLabelText("翻译字幕"));
  await userEvent.selectOptions(screen.getByLabelText("翻译为"),"en");
  await userEvent.selectOptions(screen.getByLabelText("字幕显示"),"translated");
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({translation_language:"en",subtitle_mode:"translated"}));
  await userEvent.click(screen.getByLabelText("翻译字幕"));
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({translation_language:null}));
});

it("载入历史不限时配置后不偷偷增加时长限制",async()=>{
  const {draftFromBrief}=await import("./generationDraft");
  const submit=vi.fn();
  const saved=draftFromBrief({preset:"podcast_highlights",preset_prompt:"完整故事",min_ms:null,max_ms:null,count:2});
  render(<HighlightForm ready busy={false} draft={saved} onSubmit={submit} />);
  expect(screen.getByLabelText("限制目标时长")).not.toBeChecked();
  expect(screen.getByLabelText("最短秒数")).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({min_ms:null,max_ms:null}));
});

it("旧的两个满长度文本合并后不截断，整体只提交一次",async()=>{
  const {defaultGenerationDraft}=await import("./generationDraft");
  const submit=vi.fn();
  const draft={...defaultGenerationDraft(),prompts:{podcast_highlights:"方向".repeat(6000)},instructions:"要求".repeat(6000)};
  const combined=draft.prompts.podcast_highlights+"\n\n"+draft.instructions;
  render(<HighlightForm ready busy={false} draft={draft} onSubmit={submit} />);
  expect(screen.getByLabelText("剪辑提示词")).toHaveValue(combined);
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({editing_prompt:combined}));
  expect(draft.instructions).toHaveLength(12000);
});
