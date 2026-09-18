import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OutputOrderControls } from "./OutputOrderControls";
it("转场保存失败时显示错误", async () => {
  const save=vi.fn().mockRejectedValue(new Error("保存失败"));
  render(<OutputOrderControls clips={[{instance_id:"a",segment_id:"s1",role:"body",text:"A",start_ms:0,end_ms:1000},{instance_id:"b",segment_id:"s2",role:"body",text:"B",start_ms:2000,end_ms:3000}]} busy={false} save={save} />);
  await userEvent.selectOptions(screen.getByRole("combobox",{name:"转场效果"}), "tv_static");
  expect(save).toHaveBeenCalledWith(["a","b"],{},300,"tv_static");
  expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
});

it("转场时长提交当前片段顺序并支持关闭", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<OutputOrderControls clips={[{instance_id:"a",segment_id:"s1",role:"body",text:"A",start_ms:0,end_ms:1000}]} busy={false} save={save} transitionMs={500} />);
  const select = screen.getByRole("combobox", {name: /钩子转场时长/});
  expect(select).toHaveValue("500");
  await userEvent.selectOptions(select, "0");
  expect(save).toHaveBeenCalledWith(["a"], {}, 0);
});
