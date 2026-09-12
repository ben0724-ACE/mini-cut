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
