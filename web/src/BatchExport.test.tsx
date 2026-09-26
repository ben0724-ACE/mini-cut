import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BatchExport } from "./BatchExport";
import { startOutputExport, startOutputExportBatch } from "./api";
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
it("批量统一画幅允许单条覆盖",async()=>{
  render(<BatchExport project="p" collection="c" outputs={[{output_id:"a",title:"A",revision:1}]} selected={["a"]} disabled={false} />);
  await userEvent.click(screen.getByText("批量画幅与单条覆盖"));
  await userEvent.selectOptions(screen.getByLabelText("批量比例"),"16:9");
  await userEvent.click(screen.getByLabelText("单独设置 A"));
  await userEvent.selectOptions(screen.getByLabelText("A比例"),"9:16");
  await userEvent.click(screen.getByRole("button",{name:"导出已选作品"}));
  expect(startOutputExportBatch).toHaveBeenLastCalledWith("p","c",expect.anything(),expect.objectContaining({aspect_ratio:"16:9"}),expect.any(String),{a:{aspect_ratio:"9:16",resolution:1080,fit:"pad"}});
});
it("批量提交后将所有任务交给结果页导航",async()=>{
  const onSubmitted=vi.fn();
  render(<BatchExport project="p" collection="c" outputs={[{output_id:"a",title:"A",revision:1},{output_id:"b",title:"B",revision:1}]} selected={["a","b"]} disabled={false} onSubmitted={onSubmitted} />);
  await userEvent.click(screen.getByRole("button",{name:"导出已选作品"}));
  expect(onSubmitted).toHaveBeenCalledWith([{outputId:"a",taskId:"a"},{outputId:"b",taskId:"b"}]);
});
