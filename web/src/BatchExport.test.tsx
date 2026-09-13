import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BatchExport } from "./BatchExport";
import { startOutputExport } from "./api";
vi.mock("./api",()=>({recoverOutputExport:vi.fn().mockResolvedValue(null),readOutputExport:vi.fn(),startOutputExport:vi.fn().mockResolvedValue({task_id:"retry",status:"succeeded",result:{media_url:"/retry",subtitle_url:"/srt"},error:null}),startOutputExportBatch:vi.fn().mockResolvedValue([{task_id:"a",status:"succeeded",result:{media_url:"/good",subtitle_url:"/srt"},error:null},{task_id:"b",status:"failed",result:null,error:"坏片段"}])}));
it("批量部分失败只重试失败作品，失败不能下载",async()=>{
  render(<BatchExport project="p" collection="c" outputs={[{output_id:"a",title:"A",revision:1},{output_id:"b",title:"B",revision:1}]} selected={["a","b"]} disabled={false} />);
  await userEvent.click(screen.getByRole("button",{name:"导出已选作品"}));
  expect(await screen.findByRole("link",{name:"下载 A"})).toHaveAttribute("href","/good");
  expect(screen.queryByRole("link",{name:"下载 B"})).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"重试 B"}));
  expect(startOutputExport).toHaveBeenCalledWith("p","c","b",1,expect.anything(),expect.any(String));
  expect(await screen.findByRole("link",{name:"下载 B"})).toHaveAttribute("href","/retry");
});
