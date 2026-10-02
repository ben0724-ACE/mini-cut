import type { OutputExportTask } from "./api";

export const exportTaskStatus: Record<OutputExportTask["status"], string> = {
  pending: "等待导出",
  running: "正在导出",
  succeeded: "导出完成",
  failed: "导出失败",
  cancelled: "已取消",
};
