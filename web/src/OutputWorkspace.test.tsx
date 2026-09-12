import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { OutputWorkspace } from "./OutputWorkspace";
vi.mock("./api", async original => ({...await original<typeof import("./api")>(), getHighlights: vi.fn().mockResolvedValue({asset_id:"source",outputs:[{output_id:"video-1",title:"作品A",reason:"理由A",revision:1,clips:[]},{output_id:"video-2",title:"作品B",reason:"理由B",revision:2,clips:[]}]})}));
it("独立作品入口只显示指定计划，不串其他作品", async () => {
  const view = render(<OutputWorkspace project="demo" collection="one" output="video-1" />);
  expect(await screen.findByRole("heading",{name:"作品A"})).toBeInTheDocument();
  view.rerender(<OutputWorkspace key="video-2" project="demo" collection="one" output="video-2" />);
  expect(await screen.findByRole("heading",{name:"作品B"})).toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:"作品A"})).not.toBeInTheDocument();
});
