import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OutputItemEditor } from "./OutputItemEditor";

it("保存失败保留修改文字，不假报成功；跳转使用原时间", async () => {
  const jump=vi.fn(); const save=vi.fn().mockRejectedValue(new Error("磁盘不可写"));
  render(<OutputItemEditor clip={{instance_id:"i",segment_id:"source",role:"body",text:"原文",start_ms:2000,end_ms:3000}} busy={false} onSave={save} onJump={jump} />);
  await userEvent.clear(screen.getByLabelText("字幕 i")); await userEvent.type(screen.getByLabelText("字幕 i"), "术语更正");
  await userEvent.click(screen.getByRole("button",{name:"保存字幕"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("磁盘不可写");
  expect(screen.queryByText("已保存")).not.toBeInTheDocument();
  expect(screen.getByLabelText("字幕 i")).toHaveValue("术语更正");
  await userEvent.click(screen.getByRole("button",{name:"跳转 2.00 秒"})); expect(jump).toHaveBeenCalledOnce();
});
