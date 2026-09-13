import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OutputOrderControls } from "./OutputOrderControls";
it("上移传递实例顺序，保存失败不假报成功", async () => {
  const save=vi.fn().mockRejectedValue(new Error("保存失败"));
  render(<OutputOrderControls clips={[{instance_id:"a",segment_id:"s1",role:"body",text:"A",start_ms:0,end_ms:1000},{instance_id:"b",segment_id:"s2",role:"body",text:"B",start_ms:2000,end_ms:3000}]} busy={false} save={save} />);
  await userEvent.click(screen.getByRole("button",{name:"上移 b"}));
  expect(save).toHaveBeenCalledWith(["b","a"],{});
  expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
});
