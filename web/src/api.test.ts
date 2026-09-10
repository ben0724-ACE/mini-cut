import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, renderAndWait } from "./api";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("renderAndWait", () => {
  it("polls a render task and builds only current-project download URLs", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("crypto", { randomUUID: () => "render-1" });
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            task_id: "render-1",
            status: "pending",
            result: null,
            error: null,
          }),
          { status: 202 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            task_id: "render-1",
            status: "succeeded",
            result: {
              duration_ms: 2_500,
              output_path: "/private/untrusted/result.mp4",
            },
            error: null,
          }),
        ),
      );
    vi.stubGlobal("fetch", fetch);

    const pending = renderAndWait("demo", "asset-1", "final.mp4");
    await vi.advanceTimersByTimeAsync(500);

    await expect(pending).resolves.toEqual({
      media_url: "/api/projects/demo/media/exports/final.mp4",
      subtitle_url: "/api/projects/demo/media/exports/final.srt",
      duration_ms: 2_500,
    });
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/projects/demo/tasks/render-1",
    );
  });

  it("rejects an unsafe output name before submitting", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);

    await expect(
      renderAndWait("demo", "asset-1", "../outside.mp4"),
    ).rejects.toBeInstanceOf(ApiError);
    expect(fetch).not.toHaveBeenCalled();
  });
});
