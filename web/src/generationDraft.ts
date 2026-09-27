import presetDefaults from "../../src/minicut/preset_prompts.json";
import type { HighlightBrief } from "./HighlightForm";

export interface GenerationDraft {
  preset: string;
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
    preset: "podcast_highlights", prompts: {...presetDefaults}, instructions: "",
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
