import { it,expect,vi } from "vitest";
import { fireEvent,render,screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GeometrySettings } from "./GeometrySettings";
it("默认原始比例和完整加边框，支持竖屏选择",async()=>{const change=vi.fn();render(<GeometrySettings value={{}} onChange={change} />);expect(screen.getByLabelText("导出适配")).toHaveValue("pad");await userEvent.selectOptions(screen.getByLabelText("导出比例"),"9:16");expect(change).toHaveBeenCalledWith({aspect_ratio:"9:16",resolution:1080,fit:"pad"});});
it("自由裁剪允许独立裁边，并限制反向边界以保留有效画面",async()=>{
  const change=vi.fn();render(<GeometrySettings value={{crop_left:20}} onChange={change} />);
  await userEvent.click(screen.getByText("自由裁剪画面"));
  fireEvent.change(screen.getByLabelText("导出裁去右侧（%）"),{target:{value:"90"}});
  expect(change).toHaveBeenLastCalledWith(expect.objectContaining({crop_left:20,crop_right:75}));
  await userEvent.click(screen.getByText("重置裁剪"));expect(change).toHaveBeenLastCalledWith(expect.objectContaining({crop_left:0,crop_right:0,crop_top:0,crop_bottom:0}));
});
