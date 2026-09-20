import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OutputItemEditor } from "./OutputItemEditor";

it("保存失败保留修改文字，不假报成功；跳转使用原时间", async () => {
  const jump=vi.fn(); const save=vi.fn().mockRejectedValue(new Error("磁盘不可写"));
  render(<OutputItemEditor clip={{instance_id:"i",segment_id:"source",role:"body",text:"原文",start_ms:2000,end_ms:3000}} busy={false} onSave={save} onJump={jump} />);
  await userEvent.click(screen.getByLabelText("编辑字幕 i"));
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
  await userEvent.click(screen.getByLabelText("编辑字幕 i"));
  expect(screen.queryByText(/原文：/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"开始 −"}));
  await userEvent.click(screen.getByRole("button",{name:"保存范围"}));
  expect(save).toHaveBeenCalledWith({source_start_ms:1500,source_end_ms:3000});
});

it("四个方向均可调整，步长可选",async()=>{
  const save=vi.fn().mockResolvedValue(undefined);
  render(<OutputItemEditor clip={{instance_id:"i",segment_id:"s",role:"body",text:"字幕",start_ms:2000,end_ms:6000}} busy={false} onSave={save} onJump={vi.fn()} durationMs={10000} />);
  await userEvent.click(screen.getByLabelText("编辑字幕 i"));
  await userEvent.click(screen.getByText("开始 ＋"));expect(screen.getByLabelText("开始 i")).toHaveValue(2.5);
  await userEvent.click(screen.getByText("结束 −"));expect(screen.getByLabelText("结束 i")).toHaveValue(5.5);
  await userEvent.selectOptions(screen.getByLabelText("步长 i"),"1");
  await userEvent.click(screen.getByText("开始 −"));await userEvent.click(screen.getByText("结束 ＋"));
  expect(screen.getByLabelText("开始 i")).toHaveValue(1.5);expect(screen.getByLabelText("结束 i")).toHaveValue(6.5);
});

it("手动换行预览时间，失败保留文本，确认后才保存分句",async()=>{
  const preview=vi.fn().mockRejectedValueOnce(new Error("文字与原转录不一致")).mockResolvedValue([{text:"多少？",start_ms:0,end_ms:1000},{text:"我觉得努力比较多。",start_ms:1000,end_ms:3000}]);
  const apply=vi.fn().mockRejectedValue(new Error("版本冲突"));
  render(<OutputItemEditor clip={{instance_id:"i",segment_id:"s",role:"body",text:"多少我觉得努力比较多",transcript_text:"多少我觉得努力比较多",start_ms:0,end_ms:3000}} busy={false} onSave={vi.fn()} onJump={vi.fn()} onSplitPreview={preview} onSplitApply={apply} />);
  await userEvent.click(screen.getByLabelText("编辑字幕 i"));
  await userEvent.clear(screen.getByLabelText("字幕 i"));
  await userEvent.type(screen.getByLabelText("字幕 i"),"多少？{Enter}我觉得努力比较多。");
  await userEvent.click(screen.getByRole("button",{name:"预览分句时间"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("文字与原转录不一致");
  expect(screen.getByLabelText("字幕 i")).toHaveValue("多少？\n我觉得努力比较多。");
  await userEvent.click(screen.getByRole("button",{name:"预览分句时间"}));
  expect(await screen.findByText("0.00–1.00 秒")).toBeInTheDocument();
  expect(apply).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button",{name:"确认分句"}));
  expect(apply).toHaveBeenCalledWith(["多少？","我觉得努力比较多。"]);
  expect(await screen.findByRole("alert")).toHaveTextContent("版本冲突");
  expect(screen.getByRole("button",{name:"确认分句"})).toBeInTheDocument();
});

it("默认收起仅显示字幕预览，折叠保留字幕和时间草稿",async()=>{
  render(<OutputItemEditor clip={{instance_id:"i",segment_id:"s",role:"body",text:"你就把它分享出来",start_ms:2000,end_ms:4000}} busy={false} onSave={vi.fn()} onJump={vi.fn()} />);
  expect(screen.getByRole("button",{name:"保存字幕"})).not.toBeVisible();
  expect(screen.getByText("你就把它分享出来",{selector:"span"})).toBeVisible();
  const summary=screen.getByLabelText("编辑字幕 i");
  await userEvent.click(summary);
  await userEvent.clear(screen.getByLabelText("字幕 i"));
  await userEvent.type(screen.getByLabelText("字幕 i"),"修改后的字幕");
  await userEvent.click(screen.getByText("开始 ＋"));
  await userEvent.click(summary);
  expect(screen.getByRole("button",{name:"保存字幕"})).not.toBeVisible();
  expect(screen.getByText("未保存")).toBeVisible();
  await userEvent.click(summary);
  expect(screen.getByLabelText("字幕 i")).toHaveValue("修改后的字幕");
  expect(screen.getByLabelText("开始 i")).toHaveValue(2.5);
});
