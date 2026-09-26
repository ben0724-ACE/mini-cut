import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

vi.mock("./api", async (original) => ({
  ...await original<typeof import("./api")>(),
  listProjects: vi.fn().mockResolvedValue([{ project_id: "old", name: "旧项目", asset_count: 0 }]),
  getProject: vi.fn().mockResolvedValue({ project_id: "old", name: "旧项目", asset_count: 0, asset_ids: [] }),
  listAssets: vi.fn().mockResolvedValue([]),
  getHighlights:vi.fn().mockResolvedValue({collection_id:"c",asset_id:"asset",brief:{},notes:[],outputs:[{output_id:"video-1",title:"导出作品",social_copy:"这是一段发布简介。",reason:"",revision:1,duration_ms:1000,clips:[]}]}),
  readOutputExport:vi.fn().mockResolvedValue({task_id:"task-1",status:"succeeded",error:null,result:{output_id:"video-1",revision:1,duration_ms:1000,media_url:"/video.mp4",cover_url:"/cover.jpg",subtitle_url:"/video.srt"}}),
}));
afterEach(() => { cleanup(); window.history.replaceState({}, "", "/"); });
it("从项目中心进入项目并返回，无需输入 ID，支持浏览器导航", async () => {
  window.history.replaceState({}, "", "/");
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "进入旧项目" }));
  expect(await screen.findByRole("region",{name:"素材库"})).toBeInTheDocument();
  expect(window.location.search).toBe("?project=old");
  await user.click(screen.getByRole("button", { name: "我的项目" }));
  expect(await screen.findByRole("button", { name: "进入旧项目" })).toBeInTheDocument();
  window.history.replaceState({}, "", "/?project=old");
  window.dispatchEvent(new PopStateEvent("popstate"));
  expect(await screen.findByRole("region",{name:"素材库"})).toBeInTheDocument();
});
it("可从持久化任务 URL 直接恢复独立导出结果页",async()=>{
  window.history.replaceState({},"","/?project=old&view=exports&collection=c&output=video-1&task=task-1");
  render(<App />);
  expect(await screen.findByRole("region",{name:"导出结果"})).toBeInTheDocument();
  expect(screen.getByRole("link",{name:"下载视频"})).toHaveAttribute("href","/video.mp4");
  expect(screen.getByRole("link",{name:"下载封面"})).toHaveAttribute("href","/cover.jpg");
  expect(screen.getByText("这是一段发布简介。")).toBeInTheDocument();
});
