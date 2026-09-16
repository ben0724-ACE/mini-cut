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

it("手动向前补范围可保存，字幕区域只出现一次", async () => {
  const save=vi.fn().mockResolvedValue(undefined);
  render(<OutputItemEditor clip={{instance_id:"i",segment_id:"source",role:"body",text:"旧字幕",source_text:"原始转录",start_ms:2000,end_ms:3000}} busy={false} onSave={save} onJump={vi.fn()} />);
  expect(screen.queryByText(/原文：/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"开始 −"}));
  await userEvent.click(screen.getByRole("button",{name:"保存范围"}));
  expect(save).toHaveBeenCalledWith({source_start_ms:1500,source_end_ms:3000});
});

it("四个方向均可调整，步长和拖动手柄可用",async()=>{
  const save=vi.fn().mockResolvedValue(undefined);
  render(<OutputItemEditor clip={{instance_id:"i",segment_id:"s",role:"body",text:"字幕",start_ms:2000,end_ms:6000}} busy={false} onSave={save} onJump={vi.fn()} durationMs={10000} />);
  await userEvent.click(screen.getByText("开始 ＋"));expect(screen.getByLabelText("开始 i")).toHaveValue(2.5);
  await userEvent.click(screen.getByText("结束 −"));expect(screen.getByLabelText("结束 i")).toHaveValue(5.5);
  await userEvent.selectOptions(screen.getByLabelText("步长 i"),"1");
  await userEvent.click(screen.getByText("开始 −"));await userEvent.click(screen.getByText("结束 ＋"));
  expect(screen.getByLabelText("开始 i")).toHaveValue(1.5);expect(screen.getByLabelText("结束 i")).toHaveValue(6.5);
});
