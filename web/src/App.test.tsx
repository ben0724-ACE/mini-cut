import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

vi.mock("./api", async (original) => ({
  ...await original<typeof import("./api")>(),
  listProjects: vi.fn().mockResolvedValue([{ project_id: "old", name: "旧项目", asset_count: 0 }]),
  getProject: vi.fn().mockResolvedValue({ project_id: "old", name: "旧项目", asset_count: 0, asset_ids: [] }),
  listAssets: vi.fn().mockResolvedValue([]),
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
