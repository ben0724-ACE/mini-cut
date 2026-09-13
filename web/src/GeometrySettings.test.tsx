import { it,expect,vi } from "vitest";
import { render,screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GeometrySettings } from "./GeometrySettings";
it("默认原始比例和完整加边框，支持竖屏选择",async()=>{const change=vi.fn();render(<GeometrySettings value={{}} onChange={change} />);expect(screen.getByLabelText("导出适配")).toHaveValue("pad");await userEvent.selectOptions(screen.getByLabelText("导出比例"),"9:16");expect(change).toHaveBeenCalledWith({aspect_ratio:"9:16",resolution:1080,fit:"pad"});});
