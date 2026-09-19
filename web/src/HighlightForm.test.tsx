import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HighlightForm } from "./HighlightForm";

it("未转录不能生成，切换预设保留文本和高级参数", async () => {
  const view = render(<HighlightForm ready={false} busy={false} onSubmit={vi.fn()} />);
  expect(screen.getByRole("button", {name: "生成候选"})).toBeDisabled();
  await userEvent.type(screen.getByLabelText("剪辑要求"), "保留反方论述");
  await userEvent.selectOptions(screen.getByLabelText("预设"), "opinion_first");
  expect(screen.getByLabelText("剪辑要求")).toHaveValue("保留反方论述");
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
  await userEvent.clear(screen.getByLabelText("预设提示词"));
  await userEvent.type(screen.getByLabelText("预设提示词"),"选择完整的幽默故事");
  await userEvent.clear(screen.getByLabelText("数量"));
  await userEvent.type(screen.getByLabelText("数量"),"1");
  expect(screen.getByLabelText("源内容重复上限")).toBeDisabled();
  await userEvent.click(screen.getByRole("button",{name:"生成候选"}));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({preset_prompt:"选择完整的幽默故事",max_source_overlap:1,count:1}));
});

it("清理预设说明连续模式限制，观点预设不自动开启钩子", async () => {
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
