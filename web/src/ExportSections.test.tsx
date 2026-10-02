import {expect,it} from "vitest";
import {render,screen} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {ExportSections} from "./ExportSections";
it("默认画面，切换保留封面与画面草稿，共用导出按钮始终可见",async()=>{
  const user=userEvent.setup();render(<><ExportSections cover={<input aria-label="封面标题"/>}><input aria-label="画面设置"/></ExportSections><button>导出作品</button></>);
  expect(screen.getByRole("button",{name:"画面"})).toHaveAttribute("aria-pressed","true");expect(screen.getByLabelText("封面标题")).not.toBeVisible();await user.type(screen.getByLabelText("画面设置"),"720");await user.click(screen.getByRole("button",{name:"封面"}));await user.type(screen.getByLabelText("封面标题"),"保留草稿");expect(screen.getByRole("button",{name:"导出作品"})).toBeVisible();await user.click(screen.getByRole("button",{name:"画面"}));expect(screen.getByLabelText("画面设置")).toHaveValue("720");await user.click(screen.getByRole("button",{name:"封面"}));expect(screen.getByLabelText("封面标题")).toHaveValue("保留草稿");
});
