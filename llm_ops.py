from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from astrbot.core.astr_main_agent import _get_session_conv
from astrbot.core.astr_main_agent_resources import CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT
from astrbot.core.platform.message_session import MessageSession

from .exceptions import DidaConfigurationError, DidaLlmIntentError
from .time_utils import now_in_timezone
from .types import DidaPluginSettings

_JSON_FENCE_PATTERN = re.compile(
    r"```(?:json)?\s*(\{[\s\S]*?\})\s*```",
    re.IGNORECASE,
)
_JSON_OBJECT_PATTERN = re.compile(r"(\{[\s\S]*\})")

_DEFAULT_LLM_TASK_OPS_PROMPT = """You are a Dida365 task operation intent parser.
Your only job is to convert the user's natural-language instruction into one JSON object.
Do not explain your reasoning. Do not wrap the JSON in Markdown unless required by the model.
This phase supports these executable actions: create_task, complete_task, update_task, move_task, delete_task, batch_complete_tasks.
If the user asks for another unsupported action, still report the best matching action name, but do not rewrite it into a supported action.

Rules:
1. Output exactly one JSON object.
2. Never invent missing facts. Leave unknown fields as empty strings and use an empty object for update_fields when needed.
3. For create_task, put the new task title in title.
4. For complete_task, update_task, move_task, and delete_task, put the task reference phrase in target_task_query.
5. project should be the current/source project name or identifier only if the user explicitly mentions it and it helps disambiguate the task.
6. target_project should only be used for move_task.
7. due_date must use YYYY-MM-DD when only a date is known.
8. due_datetime must use YYYY-MM-DD HH:MM when a specific local time is known.
9. The top-level priority and content fields are only for create_task.
10. For update_task, put only changed fields into update_fields. Supported keys are due_date, due_datetime, priority, and content.
11. For batch_complete_tasks, batch_scope must be one of: today, overdue, unfinished_project.
12. For unfinished_project batch scope, project must contain the project reference.
13. confidence should be a number between 0 and 1.
14. ambiguity_reason should explain what is unclear, or be an empty string.
15. risk_level should be "low" for create_task, complete_task, update_task. risk_level should be "high" for move_task, delete_task, batch_complete_tasks.
16. When the user says to cancel, remove, delete, drop, or no longer do an existing task, prefer delete_task, not create_task.
17. If the user refers to an existing task using labels like "Task: Wash up", "任务: 洗澡", or quoted text, copy the referenced task text into target_task_query without the label prefix when possible.
18. If the user says to cancel a previously planned task, and the instruction is about the existing task itself rather than the pending confirmation flow, treat it as delete_task.
19. If the user changes a task to a date or time, such as "move it to tomorrow", "改到明天", "推迟到周五", or "改到晚上十一点", treat that as update_task with due_date or due_datetime, not move_task.
20. Use move_task only when the target is another project, list, or folder. If there is no target project/list, do not use move_task.

Return this JSON shape:
{
  "action": "create_task",
  "risk_level": "low",
  "title": "",
  "target_task_query": "",
  "project": "",
  "target_project": "",
  "batch_scope": "",
  "due_date": "",
  "due_datetime": "",
  "priority": "",
  "content": "",
  "update_fields": {
    "due_date": "",
    "due_datetime": "",
    "priority": "",
    "content": ""
  },
  "requires_confirmation": false,
  "confidence": 0.0,
  "ambiguity_reason": ""
}

Current local time: {current_time}
Current timezone: {timezone}
User instruction:
{user_instruction}
"""


@dataclass(slots=True)
class DidaLlmTaskIntent:
    action: str
    risk_level: str
    title: str
    target_task_query: str = ""
    project: str = ""
    target_project: str = ""
    batch_scope: str = ""
    due_date: str = ""
    due_datetime: str = ""
    priority: str = ""
    content: str = ""
    update_fields: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    confidence: float | None = None
    ambiguity_reason: str = ""
    raw_text: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        raw_text: str = "",
    ) -> DidaLlmTaskIntent:
        confidence = data.get("confidence")
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = None

        update_fields = data.get("update_fields")
        if not isinstance(update_fields, dict):
            update_fields = {}

        return cls(
            action=str(data.get("action", "") or "").strip(),
            risk_level=str(data.get("risk_level", "") or "").strip().lower(),
            title=str(data.get("title", "") or "").strip(),
            target_task_query=str(data.get("target_task_query", "") or "").strip(),
            project=str(data.get("project", "") or "").strip(),
            target_project=str(data.get("target_project", "") or "").strip(),
            batch_scope=str(data.get("batch_scope", "") or "").strip().lower(),
            due_date=str(data.get("due_date", "") or "").strip(),
            due_datetime=str(data.get("due_datetime", "") or "").strip(),
            priority=str(data.get("priority", "") or "").strip().lower(),
            content=str(data.get("content", "") or "").strip(),
            update_fields=update_fields,
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            confidence=confidence_value,
            ambiguity_reason=str(data.get("ambiguity_reason", "") or "").strip(),
            raw_text=raw_text,
            raw_data=data,
        )


class DidaLlmTaskIntentParser:
    """Parse natural-language task operations with the current session LLM."""

    def __init__(self, context, settings: DidaPluginSettings) -> None:
        self.context = context
        self.settings = settings

    async def parse_task_instruction(
        self,
        event,
        instruction: str,
    ) -> DidaLlmTaskIntent:
        user_instruction = str(instruction or "").strip()
        if not user_instruction:
            raise DidaLlmIntentError(
                "No natural-language instruction was provided for Dida365 task parsing.",
            )

        provider = self.context.get_using_provider(event.unified_msg_origin)
        if not provider:
            raise DidaConfigurationError(
                "No active chat provider is configured for this session, so Dida365 natural-language task operations cannot use the LLM parser.",
            )

        conversation = await _get_session_conv(event, self.context)
        provider_settings = self.context.get_config(umo=event.unified_msg_origin).get(
            "provider_settings",
            {},
        )
        session = MessageSession.from_str(event.unified_msg_origin)
        system_prompt, persona_contexts = await self._build_persona_context(
            target_umo=event.unified_msg_origin,
            conversation_persona_id=conversation.persona_id,
            session=session,
            provider_settings=provider_settings,
        )

        timezone = self.settings.timezone
        current_time = now_in_timezone(timezone).strftime("%Y-%m-%d %H:%M")
        prompt = self._compose_prompt(
            user_instruction=user_instruction,
            current_time=current_time,
            timezone=timezone,
        )
        llm_resp = await provider.text_chat(
            prompt=prompt,
            session_id=event.unified_msg_origin,
            contexts=persona_contexts,
            system_prompt=system_prompt,
            persist=False,
        )
        completion = (llm_resp.completion_text or "").strip()
        if not completion:
            raise DidaLlmIntentError(
                "The LLM returned an empty result while parsing the Dida365 task instruction.",
            )
        return self.parse_completion_text(completion)

    @classmethod
    def parse_completion_text(cls, completion_text: str) -> DidaLlmTaskIntent:
        payload = cls._extract_json_payload(completion_text)
        return DidaLlmTaskIntent.from_dict(payload, raw_text=completion_text)

    @classmethod
    def _extract_json_payload(cls, completion_text: str) -> dict[str, Any]:
        text = str(completion_text or "").strip()
        if not text:
            raise DidaLlmIntentError("The LLM returned an empty intent payload.")

        match = _JSON_FENCE_PATTERN.search(text)
        if match:
            json_text = match.group(1)
        else:
            object_match = _JSON_OBJECT_PATTERN.search(text)
            json_text = object_match.group(1) if object_match else text

        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise DidaLlmIntentError(
                "The LLM did not return a valid JSON task intent, so the Dida365 action was not executed.",
            ) from exc

        if not isinstance(payload, dict):
            raise DidaLlmIntentError(
                "The LLM returned a non-object JSON value for the Dida365 task intent.",
            )
        return payload

    async def _build_persona_context(
        self,
        *,
        target_umo: str,
        conversation_persona_id: str | None,
        session: MessageSession,
        provider_settings: dict,
    ) -> tuple[str, list[dict]]:
        platform_name = self._resolve_platform_name(session)
        (
            _persona_id,
            persona,
            _force_applied_persona_id,
            use_webchat_special_default,
        ) = await self.context.persona_manager.resolve_selected_persona(
            umo=target_umo,
            conversation_persona_id=conversation_persona_id,
            platform_name=platform_name,
            provider_settings=provider_settings,
        )

        system_prompt = ""
        contexts: list[dict] = []
        if persona:
            if prompt := persona.get("prompt"):
                system_prompt += f"\n# Persona Instructions\n\n{prompt}\n"
            if begin_dialogs := persona.get("_begin_dialogs_processed"):
                contexts.extend(json.loads(json.dumps(begin_dialogs)))
        elif use_webchat_special_default:
            system_prompt += CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT

        return system_prompt.strip(), contexts

    def _resolve_platform_name(self, session: MessageSession) -> str:
        for platform in self.context.platform_manager.platform_insts:
            meta = platform.meta()
            if meta.id == session.platform_id:
                return meta.name
        return session.platform_id

    def _compose_prompt(
        self,
        *,
        user_instruction: str,
        current_time: str,
        timezone: str,
    ) -> str:
        template = (
            self.settings.llm_task_ops_prompt.strip() or _DEFAULT_LLM_TASK_OPS_PROMPT
        )
        replacements = {
            "current_time": current_time,
            "timezone": timezone,
            "user_instruction": user_instruction,
        }
        for key, value in replacements.items():
            template = template.replace(f"{{{key}}}", value)
        if "{user_instruction}" in (self.settings.llm_task_ops_prompt or ""):
            return template
        if self.settings.llm_task_ops_prompt.strip():
            return (
                f"{template}\n\nCurrent local time: {current_time}\n"
                f"Current timezone: {timezone}\n"
                f"User instruction:\n{user_instruction}"
            )
        return template
