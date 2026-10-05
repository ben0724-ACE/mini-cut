"""Web-facing orchestration reusing the source-bound highlight workflow."""

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import asdict, replace
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar, cast

from minicut.boundary_refinement import refine_boundaries
from minicut.deepseek_provider import DeepSeekProvider
from minicut.errors import UserInputError
from minicut.highlight_brief import HighlightBrief
from minicut.highlight_planner import HighlightPlanner
from minicut.highlight_workflow import plan_highlights
from minicut.model_journal import ModelJournal, RecordedProvider
from minicut.output_plan import OutputItem, OutputRole
from minicut.output_reader import OutputReader, source_segments
from minicut.output_reader import source_transcript as _source_transcript
from minicut.output_repository import OutputCollectionRepository
from minicut.output_sentences import split_output_sentences
from minicut.output_timeline import compile_output_timeline
from minicut.project import ProjectRepository
from minicut.semantic_segment import SemanticSegment
from minicut.sentence_boundaries import sentence_segments
from minicut.subtitle_font import resolve_selected_subtitle_font
from minicut.subtitle_style import SubtitleStyle
from minicut.text_normalization import normalize_text
from minicut.transcript import Transcript
from minicut.transcription_task import CancellationToken

_EditArgs = ParamSpec("_EditArgs")
_EditResult = TypeVar("_EditResult")


def _atomic_output_edit(
    operation: Callable[_EditArgs, _EditResult],
) -> Callable[_EditArgs, _EditResult]:
    """Keep source reads, revision checks, history and response in one boundary."""

    @wraps(operation)
    def edit(
        *args: _EditArgs.args,
        **kwargs: _EditArgs.kwargs,
    ) -> _EditResult:
        project = cast(Path, args[0] if args else kwargs["project"])
        collection_id = cast(str, args[1] if len(args) > 1 else kwargs["collection_id"])
        with OutputCollectionRepository(project, collection_id).mutation():
            return operation(*args, **kwargs)

    return edit


def generate_highlights(
    project: Path,
    asset_id: str,
    collection_id: str,
    brief: HighlightBrief,
    *,
    cancellation: CancellationToken | None = None,
) -> dict[str, object]:
    transcript = _source_transcript(project, asset_id, collection_id)
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise UserInputError("DeepSeek is not configured on the server")
    if brief.cleanup_version in {1, 2}:
        from minicut.speech_cleanup import generate_cleanup

        return generate_cleanup(
            project, asset_id, collection_id, brief, transcript, cancellation
        )
    segments = sentence_segments(transcript)
    repository = OutputCollectionRepository(project, collection_id)
    repository.write_segments(segments)
    recorded = RecordedProvider(
        DeepSeekProvider(
            key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        ),
        ModelJournal(project),
        cancellation,
    )
    planner = HighlightPlanner(
        recorded,
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        timeout=180,
    )
    workflow = asyncio.run(
        plan_highlights(planner, brief, segments, asset_id, collection_id)
    )
    duration_ms = next(
        a.duration_ms
        for a in ProjectRepository(project).read().assets
        if a.asset_id == asset_id
    )
    selection = asyncio.run(
        refine_boundaries(
            workflow.selection,
            brief,
            transcript,
            segments,
            recorded,
            planner.model,
            duration_ms,
        )
    )
    if selection.collection is not None:
        selection = replace(
            selection,
            collection=replace(
                selection.collection,
                plans=tuple(
                    split_output_sentences(p, segments, transcript)
                    for p in selection.collection.plans
                ),
            ),
        )
    if selection.collection is not None and brief.translation_language is not None:
        from minicut.subtitle_translation import translate_collection

        selection = replace(
            selection,
            collection=asyncio.run(
                translate_collection(
                    selection.collection,
                    segments,
                    transcript,
                    recorded,
                    planner.model,
                    brief.translation_language,
                    brief.subtitle_mode,
                )
            ),
        )
    outputs: list[dict[str, object]] = []
    repository = OutputCollectionRepository(project, collection_id)
    if selection.collection is not None:
        repository.write(selection.collection, segments)
        candidates = {
            candidate.candidate_id: candidate
            for candidate in selection.collection.candidates
        }
        by_id = {segment.segment_id: segment for segment in segments}
        for plan in selection.collection.plans:
            timeline = compile_output_timeline(plan, segments, asset_id)
            outputs.append(
                {
                    "output_id": plan.output_id,
                    "title": plan.title,
                    "social_copy": plan.social_copy,
                    "reason": candidates[plan.candidate_id].reason,
                    "revision": plan.revision,
                    "hook_transition_ms": plan.hook_transition_ms,
                    "hook_transition_kind": plan.hook_transition_kind,
                    "duration_ms": timeline.estimated_duration_ms,
                    "clips": [
                        {
                            "instance_id": item.instance_id,
                            "segment_id": item.segment_id,
                            "role": item.role.value,
                            "text": by_id[item.segment_id].text,
                            "start_ms": item.source_start_ms
                            if item.source_start_ms is not None
                            else by_id[item.segment_id].start_ms,
                            "end_ms": item.source_end_ms
                            if item.source_end_ms is not None
                            else by_id[item.segment_id].end_ms,
                        }
                        for item in plan.items
                    ],
                }
            )
    result: dict[str, object] = {
        "collection_id": collection_id,
        "asset_id": asset_id,
        "brief": brief.to_dict(),
        "source_duration_ms": duration_ms,
        "notes": list(selection.notes),
        "outputs": outputs,
        "model_requests": recorded.receipts,
    }
    repository.write_highlight_result(result)
    return read_highlights(project, collection_id)


def read_highlights(project: Path, collection_id: str) -> dict[str, object]:
    repository = OutputCollectionRepository(project, collection_id)
    try:
        result = cast(
            dict[str, object],
            json.loads(
                (
                    project / ".minicut/highlight-results" / f"{collection_id}.json"
                ).read_text(encoding="utf-8")
            ),
        )
        if "source_duration_ms" not in result:
            duration = next(
                (
                    a.duration_ms
                    for a in ProjectRepository(project).read().assets
                    if a.asset_id == result["asset_id"]
                ),
                None,
            )
            if duration is not None:
                result["source_duration_ms"] = duration
        if repository.path.is_file():
            source = OutputReader(project, collection_id).read()
            collection, segments, transcript = (
                source.collection,
                source.segments,
                source.transcript,
            )
            if result["asset_id"] != collection.asset_id:
                raise UserInputError(
                    "Highlight result source does not match saved collection"
                )
            by_id = {segment.segment_id: segment for segment in segments}
            rows = {
                row["output_id"]: row
                for row in cast(list[dict[str, object]], result["outputs"])
            }
            for plan in collection.plans:
                row = rows[plan.output_id]
                row["workflow"] = plan.workflow
                row["title"] = plan.title
                row["social_copy"] = plan.social_copy
                row["revision"] = plan.revision
                row["hook_transition_ms"] = plan.hook_transition_ms
                row["hook_transition_kind"] = plan.hook_transition_kind
                row["subtitle_style"] = (
                    asdict(plan.subtitle_style) if plan.subtitle_style else None
                )
                row.update(
                    {
                        key: getattr(plan, key)
                        for key in (
                            "subtitle_mode",
                            "subtitle_source_scale",
                            "subtitle_translation_scale",
                            "subtitle_horizontal_percent",
                            "subtitle_bottom_percent",
                            "subtitle_order",
                        )
                    }
                )
                row["duration_ms"] = compile_output_timeline(
                    plan, segments, collection.asset_id
                ).estimated_duration_ms
                row["clips"] = [
                    {
                        "instance_id": item.instance_id,
                        "segment_id": item.segment_id,
                        "role": item.role.value,
                        "text": item.display_text
                        or item_source_text(item, by_id[item.segment_id], transcript),
                        "translation_text": item.translation_text,
                        "translation_language": item.translation_language,
                        "subtitle_mode": item.subtitle_mode,
                        "source_text": by_id[item.segment_id].text,
                        "transcript_text": item_source_text(
                            item, by_id[item.segment_id], transcript
                        ),
                        "deleted": item.deleted,
                        "cleanup_category": item.cleanup_category,
                        "start_ms": item.source_start_ms
                        if item.source_start_ms is not None
                        else by_id[item.segment_id].start_ms,
                        "end_ms": item.source_end_ms
                        if item.source_end_ms is not None
                        else by_id[item.segment_id].end_ms,
                    }
                    for item in plan.items
                ]
        return result
    except (OSError, ValueError) as error:
        raise UserInputError("Highlight result is missing or invalid") from error


@_atomic_output_edit
def edit_output_item(
    project: Path,
    collection_id: str,
    output_id: str,
    instance_id: str,
    *,
    deleted: bool | None = None,
    display_text: str | None = None,
    translation_text: str | None = None,
    subtitle_mode: str | None = None,
    source_start_ms: int | None = None,
    source_end_ms: int | None = None,
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]), collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next(
        (plan for plan in collection.plans if plan.output_id == output_id), None
    )
    if plan is None or not any(item.instance_id == instance_id for item in plan.items):
        raise UserInputError("Output item does not exist")
    if source_start_ms is not None or source_end_ms is not None:
        asset = next(
            a
            for a in ProjectRepository(project).read().assets
            if a.asset_id == collection.asset_id
        )
        if (
            source_start_ms is None
            or source_end_ms is None
            or not 0 <= source_start_ms < source_end_ms <= asset.duration_ms
        ):
            raise UserInputError("起止时间必须位于源素材内，且结束晚于开始")
    updated = replace(
        plan,
        revision=plan.revision + 1,
        items=tuple(
            replace(
                item,
                deleted=item.deleted if deleted is None else deleted,
                translation_text=(
                    None if source_start_ms is not None else item.translation_text
                )
                if translation_text is None
                else translation_text.strip(),
                subtitle_mode=item.subtitle_mode
                if subtitle_mode is None
                else subtitle_mode,
                source_start_ms=item.source_start_ms
                if source_start_ms is None
                else source_start_ms,
                source_end_ms=item.source_end_ms
                if source_end_ms is None
                else source_end_ms,
                display_text=(
                    None if source_start_ms is not None else item.display_text
                )
                if display_text is None
                else display_text.strip(),
            )
            if item.instance_id == instance_id
            else item
            for item in plan.items
        ),
    )
    repository.write(
        replace(
            collection,
            plans=tuple(
                updated if existing.output_id == output_id else existing
                for existing in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)


@_atomic_output_edit
def save_output_subtitle_settings(
    project: Path,
    collection_id: str,
    output_id: str,
    base_revision: int,
    *,
    subtitle_mode: str | None,
    subtitle_source_scale: float,
    subtitle_translation_scale: float,
    subtitle_horizontal_percent: int,
    subtitle_bottom_percent: int,
    subtitle_order: str,
    subtitle_style: dict[str, object] | None = None,
    replace_subtitle_style: bool = False,
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]), collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next((p for p in collection.plans if p.output_id == output_id), None)
    if plan is None:
        raise UserInputError("Output does not exist")
    if plan.revision != base_revision:
        raise RevisionConflict("作品已有新版本，请刷新后重试")
    style = SubtitleStyle.from_dict(subtitle_style) if subtitle_style else None
    if style:
        for font_id in (style.source_font_id, style.translation_font_id):
            if font_id:
                resolve_selected_subtitle_font(font_id)
    updated = replace(
        plan,
        revision=plan.revision + 1,
        subtitle_mode=subtitle_mode,
        subtitle_source_scale=subtitle_source_scale,
        subtitle_translation_scale=subtitle_translation_scale,
        subtitle_horizontal_percent=subtitle_horizontal_percent,
        subtitle_bottom_percent=subtitle_bottom_percent,
        subtitle_order=subtitle_order,
        subtitle_style=style
        if style or replace_subtitle_style
        else plan.subtitle_style,
    )
    repository.write(
        replace(
            collection,
            plans=tuple(
                updated if p.output_id == output_id else p for p in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)


def translate_output_subtitles(
    project: Path,
    collection_id: str,
    output_id: str,
    base_revision: int,
    language: str,
    cancellation: CancellationToken | None = None,
) -> dict[str, object]:
    from minicut.subtitle_translation import translate_collection

    repository = OutputCollectionRepository(project, collection_id)
    with repository.mutation():
        result = read_highlights(project, collection_id)
        segments = source_segments(
            project, cast(str, result["asset_id"]), collection_id
        )
        collection = repository.read(segments)
        transcript = _source_transcript(project, collection.asset_id, collection_id)
    plan = next((p for p in collection.plans if p.output_id == output_id), None)
    if plan is None:
        raise UserInputError("Output does not exist")
    if plan.revision != base_revision:
        raise RevisionConflict("作品已有新版本，请刷新后重试")
    active = [i for i in plan.items if not i.deleted]
    if any(i.translation_text and i.translation_language != language for i in active):
        raise UserInputError("已有其他语言译文；请先保留当前版本并选择相同目标语言")
    if not any(not i.translation_text for i in active):
        raise UserInputError("当前作品的字幕均已有译文")
    effective_mode = plan.subtitle_mode or next(
        (i.subtitle_mode for i in active if i.translation_text), "bilingual"
    )
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise UserInputError("DeepSeek is not configured on the server")
    recorded = RecordedProvider(
        DeepSeekProvider(
            key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        ),
        ModelJournal(project),
        cancellation,
    )
    translated = asyncio.run(
        translate_collection(
            replace(collection, plans=(plan,)),
            segments,
            transcript,
            recorded,
            os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            language,
            "bilingual" if effective_mode == "source" else effective_mode,
            only_missing=True,
        )
    ).plans[0]
    with repository.mutation():
        current = repository.read(segments)
        latest = next((p for p in current.plans if p.output_id == output_id), None)
        if latest is None or latest.revision != base_revision:
            raise RevisionConflict("翻译期间作品已修改，译文未写入；请重试")
        updated = replace(
            translated,
            revision=base_revision + 1,
            subtitle_mode=effective_mode,
        )
        repository.write(
            replace(
                current,
                plans=tuple(
                    updated if p.output_id == output_id else p for p in current.plans
                ),
            ),
            segments,
        )
        return read_highlights(project, collection_id)


@_atomic_output_edit
def reorder_output(
    project: Path,
    collection_id: str,
    output_id: str,
    order: list[str],
    roles: dict[str, str],
    hook_transition_ms: int | None = None,
    hook_transition_kind: str | None = None,
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]), collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next(
        (plan for plan in collection.plans if plan.output_id == output_id), None
    )
    if plan is None:
        raise UserInputError("Output does not exist")
    by_id = {item.instance_id: item for item in plan.items}
    if (
        len(order) != len(by_id)
        or set(order) != set(by_id)
        or not set(roles) <= set(by_id)
    ):
        raise UserInputError("Order must contain every instance exactly once")
    promoted = {
        identity
        for identity, role in roles.items()
        if role == "hook" and by_id[identity].role is OutputRole.BODY
    }
    if any(by_id[identity].deleted for identity in promoted):
        raise UserInputError("Restore the body excerpt before adding an opening hook")
    arranged: list[OutputItem] = []
    for identity in order:
        item = by_id[identity]
        target = OutputRole(roles.get(identity, item.role.value))
        if identity in promoted:
            arranged.append(
                replace(
                    item,
                    instance_id=f"{identity}-hook-v{plan.revision + 1}",
                    role=OutputRole.HOOK,
                )
            )
        elif (
            item.role is OutputRole.HOOK
            and target is OutputRole.BODY
            and any(
                other.role is OutputRole.BODY and other.segment_id == item.segment_id
                for other in plan.items
            )
        ):
            continue  # Removing the teaser leaves its existing body occurrence intact.
        else:
            arranged.append(replace(item, role=target))
    if promoted:
        hooks = [item for item in arranged if item.role is OutputRole.HOOK]
        # Promoting a teaser must not reorder or remove the complete body.
        body = [item for item in plan.items if item.role is OutputRole.BODY]
        arranged = hooks + body
    updated = replace(
        plan,
        revision=plan.revision + 1,
        items=tuple(arranged),
        hook_transition_kind=plan.hook_transition_kind
        if hook_transition_kind is None
        else hook_transition_kind,
        hook_transition_ms=plan.hook_transition_ms
        if hook_transition_ms is None
        else hook_transition_ms,
    )
    repository.write(
        replace(
            collection,
            plans=tuple(
                updated if existing.output_id == output_id else existing
                for existing in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)


def output_versions(
    project: Path, collection_id: str, output_id: str
) -> list[dict[str, object]]:
    history = OutputReader(project, collection_id).history(output_id)
    segments, transcript = history.source.segments, history.source.transcript
    by_id = {segment.segment_id: segment for segment in segments}
    return [
        {
            "revision": plan.revision,
            "subtitle_style": asdict(plan.subtitle_style)
            if plan.subtitle_style
            else None,
            "hook_transition_ms": plan.hook_transition_ms,
            "hook_transition_kind": plan.hook_transition_kind,
            **{
                key: getattr(plan, key)
                for key in (
                    "subtitle_mode",
                    "subtitle_source_scale",
                    "subtitle_translation_scale",
                    "subtitle_horizontal_percent",
                    "subtitle_bottom_percent",
                    "subtitle_order",
                )
            },
            "duration_ms": compile_output_timeline(
                plan, segments, history.source.collection.asset_id
            ).estimated_duration_ms,
            "clips": [
                {
                    "instance_id": item.instance_id,
                    "segment_id": item.segment_id,
                    "role": item.role.value,
                    "translation_text": item.translation_text,
                    "translation_language": item.translation_language,
                    "subtitle_mode": item.subtitle_mode,
                    "deleted": item.deleted,
                    "cleanup_category": item.cleanup_category,
                    "text": item.display_text
                    or item_source_text(item, by_id[item.segment_id], transcript),
                    "start_ms": item.source_start_ms
                    if item.source_start_ms is not None
                    else by_id[item.segment_id].start_ms,
                    "end_ms": item.source_end_ms
                    if item.source_end_ms is not None
                    else by_id[item.segment_id].end_ms,
                }
                for item in plan.items
            ],
        }
        for plan in history.plans
    ]


def item_source_text(
    item: OutputItem, segment: SemanticSegment, transcript: Transcript
) -> str:
    if item.source_start_ms is None or item.source_end_ms is None:
        return segment.text
    return (
        normalize_text(
            " ".join(
                w.text
                for w in transcript.words
                if w.start_ms < item.source_end_ms and w.end_ms > item.source_start_ms
            )
        )
        or "（此范围无转录文字）"
    )


class RevisionConflict(UserInputError):
    """The editor must reload before overwriting a newer revision."""


@_atomic_output_edit
def save_output_ranges(
    project: Path,
    collection_id: str,
    output_id: str,
    base_revision: int,
    ranges: list[dict[str, object]],
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    asset_id = cast(str, result["asset_id"])
    segments = source_segments(project, asset_id, collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next((p for p in collection.plans if p.output_id == output_id), None)
    if plan is None:
        raise UserInputError("作品不存在")
    if plan.revision != base_revision:
        raise RevisionConflict("作品已有新版本，请刷新后重新调整；草稿尚未保存")
    duration = next(
        a.duration_ms
        for a in ProjectRepository(project).read().assets
        if a.asset_id == asset_id
    )
    changes = {cast(str, row["instance_id"]): row for row in ranges}
    if (
        not changes
        or len(changes) != len(ranges)
        or not changes.keys() <= {i.instance_id for i in plan.items}
    ):
        raise UserInputError("片段列表为空、重复或不存在")
    for row in ranges:
        start, end = row["source_start_ms"], row["source_end_ms"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= duration
        ):
            raise UserInputError("起止时间必须位于源素材内，且结束晚于开始")
    items = tuple(
        replace(
            item,
            source_start_ms=cast(int, changes[item.instance_id]["source_start_ms"]),
            source_end_ms=cast(int, changes[item.instance_id]["source_end_ms"]),
            display_text=None,
            translation_text=None,
        )
        if item.instance_id in changes
        else item
        for item in plan.items
    )
    updated = replace(plan, revision=plan.revision + 1, items=items)
    repository.write(
        replace(
            collection,
            plans=tuple(
                updated if p.output_id == output_id else p for p in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)


@_atomic_output_edit
def split_saved_output(
    project: Path, collection_id: str, output_id: str, base_revision: int
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    asset = cast(str, result["asset_id"])
    segments = source_segments(project, asset, collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next((p for p in collection.plans if p.output_id == output_id), None)
    if plan is None:
        raise UserInputError("作品不存在")
    if plan.revision != base_revision:
        raise UserInputError("版本冲突，请刷新后重试")
    updated = split_output_sentences(
        plan, segments, _source_transcript(project, asset, collection_id)
    )
    if updated.items != plan.items:
        updated = replace(updated, revision=plan.revision + 1)
        repository.write(
            replace(
                collection,
                plans=tuple(
                    updated if p.output_id == output_id else p for p in collection.plans
                ),
            ),
            segments,
        )
    return read_highlights(project, collection_id)


@_atomic_output_edit
def manual_split_output(
    project: Path,
    collection_id: str,
    output_id: str,
    instance_id: str,
    base_revision: int,
    lines: list[str],
    apply: bool,
) -> dict[str, object]:
    from minicut.manual_split import split_item_by_lines

    result = read_highlights(project, collection_id)
    asset = cast(str, result["asset_id"])
    segments = source_segments(project, asset, collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next((p for p in collection.plans if p.output_id == output_id), None)
    if plan is None:
        raise UserInputError("作品不存在")
    if plan.revision != base_revision:
        raise UserInputError("版本冲突，请刷新后重试")
    item = next((i for i in plan.items if i.instance_id == instance_id), None)
    if item is None:
        raise UserInputError("片段不存在")
    segment = next(s for s in segments if s.segment_id == item.segment_id)
    parts = split_item_by_lines(
        item,
        segment,
        _source_transcript(project, asset, collection_id),
        lines,
        plan.revision + 1,
    )
    if not apply:
        return {
            "ranges": [
                {
                    "text": part.display_text,
                    "start_ms": part.source_start_ms,
                    "end_ms": part.source_end_ms,
                }
                for part in parts
            ]
        }
    updated = replace(
        plan,
        revision=plan.revision + 1,
        items=tuple(
            part
            for old in plan.items
            for part in (parts if old.instance_id == instance_id else (old,))
        ),
    )
    repository.write(
        replace(
            collection,
            plans=tuple(
                updated if p.output_id == output_id else p for p in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)


@_atomic_output_edit
def rename_output(
    project: Path, collection_id: str, output_id: str, base_revision: int, title: str
) -> dict[str, object]:
    title = title.strip()
    if not title or len(title) > 200:
        raise UserInputError("作品名需为 1–200 个字符")
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]), collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next((p for p in collection.plans if p.output_id == output_id), None)
    if plan is None:
        raise UserInputError("作品不存在")
    if plan.revision != base_revision:
        raise RevisionConflict("作品已有新版本，请刷新后重试")
    repository.write(
        replace(
            collection,
            plans=tuple(
                replace(p, title=title, revision=p.revision + 1)
                if p.output_id == output_id
                else p
                for p in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)
