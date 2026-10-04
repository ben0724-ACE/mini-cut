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
  draft.prompts[draft.preset] = brief.editing_prompt ?? combineEditingPrompt(brief.preset_prompt ?? draft.prompts[draft.preset], brief.instructions ?? "");
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
  const template = normalizeGenerationDraft(preset.draft);
  const normalized = normalizeGenerationDraft(current);
  return {
    ...normalized,
    ...(mode === "workflow" ? template : {}),
    prompts:{...normalized.prompts},
    custom_prompt:activeGenerationPrompt(template),
    custom_preset_id:preset.preset_id,
    custom_preset_name:preset.name,
  };
}

export function activeGenerationPrompt(draft:GenerationDraft):string {
  const prompt = draft.custom_preset_id ? draft.custom_prompt??draft.prompts[draft.preset] : draft.prompts[draft.preset];
  return combineEditingPrompt(prompt ?? "", draft.instructions);
}

export function combineEditingPrompt(prompt:string, instructions:string):string {
  return [prompt,instructions].filter(part=>part.length>0).join("\n\n");
}

// Legacy requirements were shared by all built-ins. Carry that text into each
// cached prompt once, without altering any submitted history or library record.
export function normalizeGenerationDraft(draft:GenerationDraft):GenerationDraft {
  if (draft.preset === "opinion_first") draft = {...draft, preset:"knowledge_digest", prompts:{...draft.prompts, knowledge_digest:draft.prompts.opinion_first??draft.prompts.knowledge_digest}};
  if (draft.preset === "clean_speech" && draft.prompts.clean_speech?.includes("连续正文模式仅选择完整表达范围")) draft = {...draft,prompts:{...draft.prompts,clean_speech:presetDefaults.clean_speech}};
  if (!draft.instructions) return draft;
  return {...draft,instructions:"",
    prompts:Object.fromEntries(Object.entries(draft.prompts).map(([key,prompt])=>[key,combineEditingPrompt(prompt,draft.instructions)])),
    custom_prompt:draft.custom_prompt == null ? draft.custom_prompt : combineEditingPrompt(draft.custom_prompt,draft.instructions),
  };
}

export function generationValidationError(draft:GenerationDraft):string {
  if (draft.preset !== "clean_speech" && (!Number.isInteger(draft.count) || draft.count < 1 || draft.count > 10 ||
      (draft.preset !== "clean_speech" && draft.limit_duration && (!Number.isFinite(draft.min_seconds) || !Number.isFinite(draft.max_seconds) || draft.min_seconds <= 0 || draft.max_seconds < draft.min_seconds)) ||
      (draft.count !== 1 && (!Number.isFinite(draft.overlap_percent) || draft.overlap_percent < 0 || draft.overlap_percent > 100)))) return "请检查数量（1–10）与时长范围、重复比例";
  if (!activeGenerationPrompt(draft)?.trim()) return "请填写剪辑提示词";
  if (activeGenerationPrompt(draft).length > 25000) return "剪辑提示词不能超过 25000 字符";
  if (draft.preset !== "clean_speech" && draft.hook_enabled && (!Number.isFinite(draft.hook_seconds) || draft.hook_seconds < 1 || draft.hook_seconds > 60)) return "开场预告目标时长需在 1–60 秒之间";
  return "";
}

export function draftFromHistory(entry:GenerationHistoryEntry):GenerationDraft {
  const draft = draftFromBrief(entry.brief);
  if (!entry.custom_preset_id) return draft;
  return {...draft,custom_preset_id:entry.custom_preset_id,custom_preset_name:entry.custom_preset_name??null,
    custom_prompt:draft.prompts[draft.preset],prompts:defaultGenerationDraft().prompts};
}
