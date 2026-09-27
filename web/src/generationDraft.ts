import presetDefaults from "../../src/minicut/preset_prompts.json";
import type { HighlightBrief } from "./HighlightForm";
import type { GenerationHistoryEntry, GenerationPreset } from "./api";

export interface GenerationDraft {
  preset: string;
  custom_preset_id?: string | null;
  custom_preset_name?: string | null;
  custom_prompt?: string | null;
  prompts: Record<string, string>;
  instructions: string;
  count: number;
  min_seconds: number;
  max_seconds: number;
  limit_duration: boolean;
  hook_enabled: boolean;
  hook_seconds: number;
  overlap_percent: number;
  body_mode: "continuous" | "compact";
  translation_enabled: boolean;
  translation_language: "zh" | "en";
  subtitle_mode: "bilingual" | "translated";
}

export function defaultGenerationDraft(): GenerationDraft {
  return {
    preset: "podcast_highlights", custom_preset_id:null, custom_preset_name:null, custom_prompt:null, prompts: {...presetDefaults}, instructions: "",
    count: 3, min_seconds: 60, max_seconds: 90, limit_duration:true, hook_enabled: false,
    hook_seconds: 5, overlap_percent: 30, body_mode: "continuous",
    translation_enabled: false, translation_language: "zh", subtitle_mode: "bilingual",
  };
}

// Only present historical fields are restored. The caller explains any defaults
// used for fields that were never recorded; they are not historical evidence.
export function draftFromBrief(brief: Partial<HighlightBrief>): GenerationDraft {
  const draft = defaultGenerationDraft();
  if (brief.preset && brief.preset in presetDefaults) draft.preset = brief.preset;
  if (brief.preset_prompt != null) draft.prompts[draft.preset] = brief.preset_prompt;
  if (brief.instructions != null) draft.instructions = brief.instructions;
  if (brief.count != null) draft.count = brief.count;
  if (brief.min_ms != null) draft.min_seconds = brief.min_ms / 1000;
  if (brief.max_ms != null) draft.max_seconds = brief.max_ms / 1000;
  if (brief.min_ms === null && brief.max_ms === null) draft.limit_duration = false;
  if (brief.hook_ms != null) {draft.hook_enabled = true; draft.hook_seconds = brief.hook_ms / 1000;}
  if (brief.max_source_overlap != null) draft.overlap_percent = brief.max_source_overlap * 100;
  if (brief.body_mode != null) draft.body_mode = brief.body_mode;
  if (brief.translation_language != null) {draft.translation_enabled = true; draft.translation_language = brief.translation_language;}
  if (brief.subtitle_mode != null) draft.subtitle_mode = brief.subtitle_mode;
  return draft;
}

export function applyGenerationPreset(current:GenerationDraft, preset:GenerationPreset, mode:"workflow"|"prompt"):GenerationDraft {
  const template = preset.draft;
  return {
    ...current,
    ...(mode === "workflow" ? template : {instructions:template.instructions}),
    prompts:{...current.prompts},
    custom_prompt:template.prompts[template.preset],
    custom_preset_id:preset.preset_id,
    custom_preset_name:preset.name,
  };
}

export function activeGenerationPrompt(draft:GenerationDraft):string {
  return draft.custom_preset_id ? draft.custom_prompt??draft.prompts[draft.preset] : draft.prompts[draft.preset];
}

export function generationValidationError(draft:GenerationDraft):string {
  if (!Number.isInteger(draft.count) || draft.count < 1 || draft.count > 10 ||
      (draft.preset !== "clean_speech" && draft.limit_duration && (!Number.isFinite(draft.min_seconds) || !Number.isFinite(draft.max_seconds) || draft.min_seconds <= 0 || draft.max_seconds < draft.min_seconds)) ||
      (draft.count !== 1 && (!Number.isFinite(draft.overlap_percent) || draft.overlap_percent < 0 || draft.overlap_percent > 100))) return "请检查数量（1–10）与时长范围、重复比例";
  if (!activeGenerationPrompt(draft)?.trim()) return "请填写预设提示词";
  if (draft.hook_enabled && (!Number.isFinite(draft.hook_seconds) || draft.hook_seconds < 1 || draft.hook_seconds > 60)) return "开场预告目标时长需在 1–60 秒之间";
  return "";
}

export function draftFromHistory(entry:GenerationHistoryEntry):GenerationDraft {
  const draft = draftFromBrief(entry.brief);
  if (!entry.custom_preset_id) return draft;
  return {...draft,custom_preset_id:entry.custom_preset_id,custom_preset_name:entry.custom_preset_name??null,
    custom_prompt:entry.brief.preset_prompt??draft.prompts[draft.preset],prompts:defaultGenerationDraft().prompts};
}
