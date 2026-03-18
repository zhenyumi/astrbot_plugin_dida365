from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from difflib import SequenceMatcher
from typing import Any

from .exceptions import DidaConfirmationError, DidaValidationError
from .llm_ops import DidaLlmTaskIntent, DidaLlmTaskIntentParser
from .service import DidaService
from .time_utils import get_timezone
from .types import DidaPluginSettings, DidaProject, DidaTask, DidaTaskWithProject


@dataclass(slots=True)
class DidaCreateTaskPlan:
    project_id: str
    project_name: str
    title: str
    content: str = ""
    due_value: str = ""
    due_display: str = "(no due date)"
    priority: int | None = None
    priority_display: str = "none"
    is_all_day: bool = False
    time_zone: str = ""
    start_value: str = ""

    def to_api_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "projectId": self.project_id,
            "title": self.title,
        }
        if self.content:
            payload["content"] = self.content
        if self.priority is not None:
            payload["priority"] = self.priority
        if self.due_value:
            payload["dueDate"] = self.due_value
            payload["isAllDay"] = self.is_all_day
            if self.start_value:
                payload["startDate"] = self.start_value
            if self.time_zone:
                payload["timeZone"] = self.time_zone
        return payload


@dataclass(slots=True)
class DidaMatchedTaskPlan:
    task_id: str
    project_id: str
    project_name: str
    title: str
    due_display: str = "(no due date)"
    priority_display: str = "none"
    status_display: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "title": self.title,
            "due_display": self.due_display,
            "priority_display": self.priority_display,
            "status_display": self.status_display,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DidaMatchedTaskPlan:
        return cls(
            task_id=str(data.get("task_id", "") or ""),
            project_id=str(data.get("project_id", "") or ""),
            project_name=str(data.get("project_name", "") or ""),
            title=str(data.get("title", "") or ""),
            due_display=str(
                data.get("due_display", "(no due date)") or "(no due date)"
            ),
            priority_display=str(data.get("priority_display", "none") or "none"),
            status_display=str(data.get("status_display", "open") or "open"),
        )


@dataclass(slots=True)
class DidaUpdateTaskPlan:
    has_due_change: bool = False
    due_value: str = ""
    due_display: str = "(unchanged)"
    is_all_day: bool = False
    time_zone: str = ""
    start_value: str = ""
    has_priority_change: bool = False
    priority: int | None = None
    priority_display: str = "(unchanged)"
    has_content_change: bool = False
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_due_change": self.has_due_change,
            "due_value": self.due_value,
            "due_display": self.due_display,
            "is_all_day": self.is_all_day,
            "time_zone": self.time_zone,
            "start_value": self.start_value,
            "has_priority_change": self.has_priority_change,
            "priority": self.priority,
            "priority_display": self.priority_display,
            "has_content_change": self.has_content_change,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DidaUpdateTaskPlan:
        return cls(
            has_due_change=bool(data.get("has_due_change", False)),
            due_value=str(data.get("due_value", "") or ""),
            due_display=str(data.get("due_display", "(unchanged)") or "(unchanged)"),
            is_all_day=bool(data.get("is_all_day", False)),
            time_zone=str(data.get("time_zone", "") or ""),
            start_value=str(data.get("start_value", "") or ""),
            has_priority_change=bool(data.get("has_priority_change", False)),
            priority=cls._to_optional_int(data.get("priority")),
            priority_display=str(
                data.get("priority_display", "(unchanged)") or "(unchanged)"
            ),
            has_content_change=bool(data.get("has_content_change", False)),
            content=str(data.get("content", "") or ""),
        )

    @staticmethod
    def _to_optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


@dataclass(slots=True)
class DidaExecutionPlan:
    action: str
    risk_level: str
    requires_confirmation: bool
    confirmation_reason: str
    request_text: str
    create_task: DidaCreateTaskPlan | None = None
    target_task: DidaMatchedTaskPlan | None = None
    update_task: DidaUpdateTaskPlan | None = None
    operation_meta: dict[str, Any] = field(default_factory=dict)
    intent_confidence: float | None = None
    ambiguity_reason: str = ""
    created_at_ts: float = 0.0
    expires_at_ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_reason": self.confirmation_reason,
            "request_text": self.request_text,
            "create_task_meta": (
                {
                    "project_id": self.create_task.project_id,
                    "project_name": self.create_task.project_name,
                    "title": self.create_task.title,
                    "content": self.create_task.content,
                    "due_value": self.create_task.due_value,
                    "due_display": self.create_task.due_display,
                    "priority": self.create_task.priority,
                    "priority_display": self.create_task.priority_display,
                    "is_all_day": self.create_task.is_all_day,
                    "time_zone": self.create_task.time_zone,
                    "start_value": self.create_task.start_value,
                }
                if self.create_task
                else None
            ),
            "target_task": self.target_task.to_dict() if self.target_task else None,
            "update_task": self.update_task.to_dict() if self.update_task else None,
            "operation_meta": self.operation_meta,
            "intent_confidence": self.intent_confidence,
            "ambiguity_reason": self.ambiguity_reason,
            "created_at_ts": self.created_at_ts,
            "expires_at_ts": self.expires_at_ts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DidaExecutionPlan:
        create_task_data = data.get("create_task_meta") or {}
        target_task_data = data.get("target_task") or {}
        update_task_data = data.get("update_task") or {}
        operation_meta = data.get("operation_meta") or {}
        if create_task_data and not isinstance(create_task_data, dict):
            raise DidaConfirmationError("Stored Dida365 confirmation data is invalid.")
        if target_task_data and not isinstance(target_task_data, dict):
            raise DidaConfirmationError("Stored Dida365 confirmation data is invalid.")
        if update_task_data and not isinstance(update_task_data, dict):
            raise DidaConfirmationError("Stored Dida365 confirmation data is invalid.")
        if operation_meta and not isinstance(operation_meta, dict):
            raise DidaConfirmationError("Stored Dida365 confirmation data is invalid.")
        return cls(
            action=str(data.get("action", "") or ""),
            risk_level=str(data.get("risk_level", "") or ""),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            confirmation_reason=str(data.get("confirmation_reason", "") or ""),
            request_text=str(data.get("request_text", "") or ""),
            create_task=(
                DidaCreateTaskPlan(
                    project_id=str(create_task_data.get("project_id", "") or ""),
                    project_name=str(create_task_data.get("project_name", "") or ""),
                    title=str(create_task_data.get("title", "") or ""),
                    content=str(create_task_data.get("content", "") or ""),
                    due_value=str(create_task_data.get("due_value", "") or ""),
                    due_display=str(
                        create_task_data.get("due_display", "(no due date)")
                        or "(no due date)"
                    ),
                    priority=cls._to_optional_int(create_task_data.get("priority")),
                    priority_display=str(
                        create_task_data.get("priority_display", "none") or "none"
                    ),
                    is_all_day=bool(create_task_data.get("is_all_day", False)),
                    time_zone=str(create_task_data.get("time_zone", "") or ""),
                    start_value=str(create_task_data.get("start_value", "") or ""),
                )
                if create_task_data
                else None
            ),
            target_task=(
                DidaMatchedTaskPlan.from_dict(target_task_data)
                if target_task_data
                else None
            ),
            update_task=(
                DidaUpdateTaskPlan.from_dict(update_task_data)
                if update_task_data
                else None
            ),
            operation_meta=operation_meta,
            intent_confidence=cls._to_optional_float(data.get("intent_confidence")),
            ambiguity_reason=str(data.get("ambiguity_reason", "") or ""),
            created_at_ts=float(data.get("created_at_ts", 0.0) or 0.0),
            expires_at_ts=float(data.get("expires_at_ts", 0.0) or 0.0),
        )

    @staticmethod
    def _to_optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_optional_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class DidaTaskOpsCoordinator:
    """Coordinate LLM parsing, validation, confirmation, and task execution."""

    PENDING_CONFIRMATION_PREFIX = "pending_task_op"
    MAX_BATCH_TASKS = 10

    def __init__(
        self,
        context,
        settings: DidaPluginSettings,
        service: DidaService,
        *,
        get_kv_data: Callable[[str, Any], Awaitable[Any]],
        put_kv_data: Callable[[str, Any], Awaitable[None]],
        delete_kv_data: Callable[[str], Awaitable[None]],
    ) -> None:
        self.context = context
        self.settings = settings
        self.service = service
        self.intent_parser = DidaLlmTaskIntentParser(context, settings)
        self._get_kv_data = get_kv_data
        self._put_kv_data = put_kv_data
        self._delete_kv_data = delete_kv_data

    async def handle_instruction(self, event, instruction: str) -> str:
        if not self.settings.enable_llm_task_ops:
            raise DidaValidationError(
                "Dida365 natural-language task operations are disabled in the plugin config.",
            )

        request_text = str(instruction or "").strip()
        if not request_text:
            raise DidaValidationError("Usage: /dida_do <natural language instruction>")

        intent = await self.intent_parser.parse_task_instruction(event, request_text)
        plan = await self._build_execution_plan(intent, request_text)
        if plan.requires_confirmation:
            await self._store_pending_confirmation(event, plan)
            return self._render_confirmation_request(plan)
        return await self._execute_plan(plan, confirmed=False)

    async def confirm_pending(self, event) -> str:
        plan = await self._load_pending_confirmation(event)
        if not plan:
            raise DidaConfirmationError(
                "There is no pending Dida365 task operation waiting for confirmation in this chat.",
            )

        if plan.expires_at_ts and time.time() > plan.expires_at_ts:
            await self._delete_kv_data(self._pending_key(event))
            raise DidaConfirmationError(
                "The pending Dida365 task operation confirmation has expired. Please run /dida_do again.",
            )

        await self._delete_kv_data(self._pending_key(event))
        return await self._execute_plan(plan, confirmed=True)

    async def cancel_pending(self, event) -> str:
        plan = await self._load_pending_confirmation(event)
        if not plan:
            return "There is no pending Dida365 task operation to cancel in this chat."
        await self._delete_kv_data(self._pending_key(event))
        return (
            "Cancelled the pending Dida365 task operation.\n"
            f"- action: {plan.action}\n"
            f"- subject: {self._plan_subject(plan)}"
        )

    async def _build_execution_plan(
        self,
        intent: DidaLlmTaskIntent,
        request_text: str,
    ) -> DidaExecutionPlan:
        intent = self._normalize_intent_for_execution(intent)
        action = (intent.action or "").strip().lower()
        if not action:
            raise DidaValidationError(
                "The LLM did not return an action for the Dida365 task request.",
            )

        builders = {
            "create_task": self._build_create_execution_plan,
            "complete_task": self._build_complete_execution_plan,
            "update_task": self._build_update_execution_plan,
            "move_task": self._build_move_execution_plan,
            "delete_task": self._build_delete_execution_plan,
            "batch_complete_tasks": self._build_batch_complete_execution_plan,
        }
        if action not in builders:
            raise DidaValidationError(
                f"The parsed Dida365 action '{action}' is not implemented yet. Supported actions in this phase are create_task, complete_task, update_task, move_task, delete_task, and batch_complete_tasks.",
            )
        return await builders[action](intent, request_text)

    def _normalize_intent_for_execution(
        self,
        intent: DidaLlmTaskIntent,
    ) -> DidaLlmTaskIntent:
        action = (intent.action or "").strip().lower()
        if action != "move_task":
            return intent
        if self._normalize_single_line(intent.target_project):
            return intent
        if not self._intent_looks_like_due_update(intent):
            return intent

        update_fields = (
            dict(intent.update_fields) if isinstance(intent.update_fields, dict) else {}
        )
        if intent.due_date and not str(update_fields.get("due_date", "") or "").strip():
            update_fields["due_date"] = intent.due_date
        if (
            intent.due_datetime
            and not str(update_fields.get("due_datetime", "") or "").strip()
        ):
            update_fields["due_datetime"] = intent.due_datetime

        return replace(
            intent,
            action="update_task",
            risk_level="low",
            target_project="",
            update_fields=update_fields,
        )

    @staticmethod
    def _intent_looks_like_due_update(intent: DidaLlmTaskIntent) -> bool:
        if str(intent.due_date or "").strip() or str(intent.due_datetime or "").strip():
            return True
        update_fields = (
            intent.update_fields if isinstance(intent.update_fields, dict) else {}
        )
        return any(
            str(update_fields.get(key, "") or "").strip()
            for key in ("due_date", "due_datetime")
        )

    async def _build_create_execution_plan(
        self,
        intent: DidaLlmTaskIntent,
        request_text: str,
    ) -> DidaExecutionPlan:
        title = self._normalize_single_line(intent.title)
        if not title:
            raise DidaValidationError(
                "The parsed Dida365 create_task intent is missing a task title.",
            )

        project_query = self._normalize_single_line(intent.project)
        if not project_query:
            project_query = self._normalize_single_line(self.settings.default_project)
        if not project_query:
            raise DidaValidationError(
                "No project was provided by the LLM and default_project is not configured. Please mention a project or set default_project first.",
            )

        project = await self._resolve_project(project_query)
        due_value, due_display, is_all_day, time_zone, start_value = (
            self._normalize_due_fields(
                due_datetime=intent.due_datetime,
                due_date_value=intent.due_date,
            )
        )
        priority, priority_display = self._normalize_priority(intent.priority)
        content = self._normalize_multiline_text(intent.content)

        risk_level = self._resolve_risk_level("create_task")
        requires_confirmation, confirmation_reason = self._compute_confirmation_policy(
            risk_level=risk_level,
            intent=intent,
        )

        return DidaExecutionPlan(
            action="create_task",
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            confirmation_reason=confirmation_reason,
            request_text=request_text,
            create_task=DidaCreateTaskPlan(
                project_id=project.id,
                project_name=project.name or project.id,
                title=title,
                content=content,
                due_value=due_value,
                due_display=due_display,
                priority=priority,
                priority_display=priority_display,
                is_all_day=is_all_day,
                time_zone=time_zone,
                start_value=start_value,
            ),
            intent_confidence=intent.confidence,
            ambiguity_reason=intent.ambiguity_reason,
        )

    async def _build_complete_execution_plan(
        self,
        intent: DidaLlmTaskIntent,
        request_text: str,
    ) -> DidaExecutionPlan:
        target_task = await self._resolve_task_reference(
            target_query=intent.target_task_query,
            project_query=intent.project,
            action="complete_task",
        )
        return DidaExecutionPlan(
            action="complete_task",
            risk_level=self._resolve_risk_level("complete_task"),
            requires_confirmation=self._compute_confirmation_policy(
                risk_level=self._resolve_risk_level("complete_task"),
                intent=intent,
            )[0],
            confirmation_reason=self._compute_confirmation_policy(
                risk_level=self._resolve_risk_level("complete_task"),
                intent=intent,
            )[1],
            request_text=request_text,
            target_task=target_task,
            intent_confidence=intent.confidence,
            ambiguity_reason=intent.ambiguity_reason,
        )

    async def _build_update_execution_plan(
        self,
        intent: DidaLlmTaskIntent,
        request_text: str,
    ) -> DidaExecutionPlan:
        target_task = await self._resolve_task_reference(
            target_query=intent.target_task_query,
            project_query=intent.project,
            action="update_task",
        )
        update_task = self._normalize_update_fields(intent)
        risk_level = self._resolve_risk_level("update_task")
        requires_confirmation, confirmation_reason = self._compute_confirmation_policy(
            risk_level=risk_level,
            intent=intent,
        )
        return DidaExecutionPlan(
            action="update_task",
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            confirmation_reason=confirmation_reason,
            request_text=request_text,
            target_task=target_task,
            update_task=update_task,
            intent_confidence=intent.confidence,
            ambiguity_reason=intent.ambiguity_reason,
        )

    async def _build_move_execution_plan(
        self,
        intent: DidaLlmTaskIntent,
        request_text: str,
    ) -> DidaExecutionPlan:
        target_task = await self._resolve_task_reference(
            target_query=intent.target_task_query,
            project_query=intent.project,
            action="move_task",
        )
        target_project_query = self._normalize_single_line(intent.target_project)
        if not target_project_query:
            raise DidaValidationError(
                "The parsed Dida365 move_task intent is missing target_project.",
            )
        target_project = await self._resolve_project(target_project_query)
        if target_project.id == target_task.project_id:
            raise DidaValidationError(
                "The matched Dida365 task is already in the target project.",
            )

        risk_level = self._resolve_risk_level("move_task")
        requires_confirmation, confirmation_reason = self._compute_confirmation_policy(
            risk_level=risk_level,
            intent=intent,
        )
        return DidaExecutionPlan(
            action="move_task",
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            confirmation_reason=confirmation_reason,
            request_text=request_text,
            target_task=target_task,
            operation_meta={
                "target_project_id": target_project.id,
                "target_project_name": target_project.name or target_project.id,
            },
            intent_confidence=intent.confidence,
            ambiguity_reason=intent.ambiguity_reason,
        )

    async def _build_delete_execution_plan(
        self,
        intent: DidaLlmTaskIntent,
        request_text: str,
    ) -> DidaExecutionPlan:
        target_task = await self._resolve_task_reference(
            target_query=intent.target_task_query,
            project_query=intent.project,
            action="delete_task",
        )
        risk_level = self._resolve_risk_level("delete_task")
        requires_confirmation, confirmation_reason = self._compute_confirmation_policy(
            risk_level=risk_level,
            intent=intent,
        )
        return DidaExecutionPlan(
            action="delete_task",
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            confirmation_reason=confirmation_reason,
            request_text=request_text,
            target_task=target_task,
            intent_confidence=intent.confidence,
            ambiguity_reason=intent.ambiguity_reason,
        )

    async def _build_batch_complete_execution_plan(
        self,
        intent: DidaLlmTaskIntent,
        request_text: str,
    ) -> DidaExecutionPlan:
        batch_scope = self._normalize_single_line(intent.batch_scope).lower()
        batch_tasks, scope_display = await self._resolve_batch_task_scope(
            batch_scope=batch_scope,
            project_query=intent.project,
        )
        if not batch_tasks:
            raise DidaValidationError(
                "The parsed Dida365 batch operation did not resolve to any tasks.",
            )
        if len(batch_tasks) > self.MAX_BATCH_TASKS:
            raise DidaValidationError(
                f"The parsed Dida365 batch operation matched {len(batch_tasks)} tasks, which exceeds the safe limit of {self.MAX_BATCH_TASKS}. Please narrow the scope first.",
            )

        risk_level = self._resolve_risk_level("batch_complete_tasks")
        requires_confirmation, confirmation_reason = self._compute_confirmation_policy(
            risk_level=risk_level,
            intent=intent,
        )
        return DidaExecutionPlan(
            action="batch_complete_tasks",
            risk_level=risk_level,
            requires_confirmation=requires_confirmation,
            confirmation_reason=confirmation_reason,
            request_text=request_text,
            operation_meta={
                "batch_scope": batch_scope,
                "scope_display": scope_display,
                "tasks": [task.to_dict() for task in batch_tasks],
            },
            intent_confidence=intent.confidence,
            ambiguity_reason=intent.ambiguity_reason,
        )

    async def _execute_plan(self, plan: DidaExecutionPlan, *, confirmed: bool) -> str:
        if plan.action == "create_task":
            return await self._execute_create_task(plan, confirmed=confirmed)
        if plan.action == "complete_task":
            return await self._execute_complete_task(plan, confirmed=confirmed)
        if plan.action == "update_task":
            return await self._execute_update_task(plan, confirmed=confirmed)
        if plan.action == "move_task":
            return await self._execute_move_task(plan, confirmed=confirmed)
        if plan.action == "delete_task":
            return await self._execute_delete_task(plan, confirmed=confirmed)
        if plan.action == "batch_complete_tasks":
            return await self._execute_batch_complete_tasks(plan, confirmed=confirmed)
        raise DidaValidationError(
            f"Unsupported Dida365 action execution: {plan.action}"
        )

    async def _execute_create_task(
        self, plan: DidaExecutionPlan, *, confirmed: bool
    ) -> str:
        if not plan.create_task:
            raise DidaValidationError("Missing create_task execution payload.")
        created_task = await self.service.client.create_task(
            plan.create_task.to_api_payload()
        )
        effective_task = created_task
        if created_task.id:
            try:
                effective_task = await self.service.client.get_task(
                    created_task.project_id,
                    created_task.id,
                )
            except Exception:
                effective_task = created_task

        due_display, due_warning = self._resolve_due_feedback(
            requested_due=plan.create_task.due_value,
            requested_display=plan.create_task.due_display,
            effective_task=effective_task,
        )
        priority_display = plan.create_task.priority_display
        if effective_task.priority is not None:
            priority_display = self.service._format_priority(effective_task)
        header = (
            "Dida365 task created after confirmation."
            if confirmed
            else "Dida365 task created."
        )
        lines = [
            header,
            f"- title: {self._display(effective_task.title or plan.create_task.title, fallback='(untitled)')}",
            f"- project: {self._display(plan.create_task.project_name, fallback=plan.create_task.project_id or '(unknown)')}",
            f"- due: {due_display}",
            f"- priority: {priority_display}",
            f"- task_id: {created_task.id or '(unknown)'}",
        ]
        if due_warning:
            lines.append(f"- due_warning: {due_warning}")
        if plan.create_task.content:
            lines.append("- content: present")
        return "\n".join(lines)

    async def _execute_complete_task(
        self, plan: DidaExecutionPlan, *, confirmed: bool
    ) -> str:
        if not plan.target_task:
            raise DidaValidationError(
                "Missing target task for complete_task execution."
            )
        await self.service.client.complete_task(
            plan.target_task.project_id, plan.target_task.task_id
        )
        effective_task = None
        try:
            effective_task = await self.service.client.get_task(
                plan.target_task.project_id,
                plan.target_task.task_id,
            )
        except Exception:
            effective_task = None
        header = (
            "Dida365 task completed after confirmation."
            if confirmed
            else "Dida365 task completed."
        )
        return "\n".join(
            [
                header,
                f"- title: {self._display((effective_task.title if effective_task else plan.target_task.title), fallback='(untitled)')}",
                f"- project: {self._display(plan.target_task.project_name, fallback=plan.target_task.project_id or '(unknown)')}",
                f"- due: {self.service._format_due(effective_task) if effective_task else plan.target_task.due_display}",
                f"- status: {self.service._format_status(effective_task) if effective_task else 'completed'}",
                f"- task_id: {plan.target_task.task_id}",
            ]
        )

    async def _execute_update_task(
        self, plan: DidaExecutionPlan, *, confirmed: bool
    ) -> str:
        if not plan.target_task or not plan.update_task:
            raise DidaValidationError(
                "Missing target task or update payload for update_task execution."
            )
        current_task = await self.service.client.get_task(
            plan.target_task.project_id,
            plan.target_task.task_id,
        )
        payload = self._build_update_payload(
            current_task=current_task,
            target_task=plan.target_task,
            update_plan=plan.update_task,
        )
        updated_task = await self.service.client.update_task(
            plan.target_task.task_id, payload
        )
        effective_task = updated_task
        if updated_task.id:
            try:
                effective_task = await self.service.client.get_task(
                    plan.target_task.project_id,
                    updated_task.id,
                )
            except Exception:
                effective_task = updated_task

        due_display, due_warning = self._resolve_due_feedback(
            requested_due=(
                plan.update_task.due_value if plan.update_task.has_due_change else ""
            ),
            requested_display=(
                plan.update_task.due_display
                if plan.update_task.has_due_change
                else self.service._format_due(current_task)
            ),
            effective_task=effective_task,
        )
        header = (
            "Dida365 task updated after confirmation."
            if confirmed
            else "Dida365 task updated."
        )
        lines = [
            header,
            f"- title: {self._display(effective_task.title or plan.target_task.title, fallback='(untitled)')}",
            f"- project: {self._display(plan.target_task.project_name, fallback=plan.target_task.project_id or '(unknown)')}",
            f"- due: {due_display}",
            f"- priority: {self.service._format_priority(effective_task)}",
            f"- task_id: {plan.target_task.task_id}",
            f"- updated_fields: {self._describe_updated_fields(plan.update_task)}",
        ]
        if plan.update_task.has_content_change:
            lines.append(
                f"- content: {'present' if effective_task.content else 'empty'}"
            )
        if due_warning:
            lines.append(f"- due_warning: {due_warning}")
        return "\n".join(lines)

    async def _execute_move_task(
        self, plan: DidaExecutionPlan, *, confirmed: bool
    ) -> str:
        if not plan.target_task:
            raise DidaValidationError("Missing target task for move_task execution.")
        target_project_id = str(plan.operation_meta.get("target_project_id", "") or "")
        target_project_name = str(
            plan.operation_meta.get("target_project_name", "") or ""
        )
        if not target_project_id:
            raise DidaValidationError("Missing target project for move_task execution.")

        current_task = await self.service.client.get_task(
            plan.target_task.project_id,
            plan.target_task.task_id,
        )
        payload = self._build_update_payload(
            current_task=current_task,
            target_task=plan.target_task,
            update_plan=DidaUpdateTaskPlan(),
        )
        payload["projectId"] = target_project_id
        moved_task = await self.service.client.update_task(
            plan.target_task.task_id, payload
        )
        effective_task = moved_task
        if moved_task.id:
            try:
                effective_task = await self.service.client.get_task(
                    target_project_id, moved_task.id
                )
            except Exception:
                effective_task = moved_task

        header = (
            "Dida365 task moved after confirmation."
            if confirmed
            else "Dida365 task moved."
        )
        return "\n".join(
            [
                header,
                f"- title: {self._display(effective_task.title or plan.target_task.title, fallback='(untitled)')}",
                f"- from_project: {self._display(plan.target_task.project_name, fallback=plan.target_task.project_id or '(unknown)')}",
                f"- to_project: {self._display(target_project_name, fallback=target_project_id or '(unknown)')}",
                f"- due: {self.service._format_due(effective_task)}",
                f"- task_id: {plan.target_task.task_id}",
            ]
        )

    async def _execute_delete_task(
        self, plan: DidaExecutionPlan, *, confirmed: bool
    ) -> str:
        if not plan.target_task:
            raise DidaValidationError("Missing target task for delete_task execution.")
        await self.service.client.delete_task(
            plan.target_task.project_id, plan.target_task.task_id
        )
        header = (
            "Dida365 task deleted after confirmation."
            if confirmed
            else "Dida365 task deleted."
        )
        return "\n".join(
            [
                header,
                f"- title: {self._display(plan.target_task.title, fallback='(untitled)')}",
                f"- project: {self._display(plan.target_task.project_name, fallback=plan.target_task.project_id or '(unknown)')}",
                f"- due: {plan.target_task.due_display}",
                f"- task_id: {plan.target_task.task_id}",
            ]
        )

    async def _execute_batch_complete_tasks(
        self, plan: DidaExecutionPlan, *, confirmed: bool
    ) -> str:
        task_dicts = plan.operation_meta.get("tasks") or []
        if not isinstance(task_dicts, list) or not task_dicts:
            raise DidaValidationError(
                "Missing batch task set for batch_complete_tasks execution."
            )

        task_plans = [
            DidaMatchedTaskPlan.from_dict(item)
            for item in task_dicts
            if isinstance(item, dict)
        ]
        completed: list[DidaMatchedTaskPlan] = []
        failed: list[str] = []
        for task_plan in task_plans:
            try:
                await self.service.client.complete_task(
                    task_plan.project_id, task_plan.task_id
                )
                completed.append(task_plan)
            except Exception as exc:
                failed.append(f"{task_plan.title}: {exc!s}")

        header = (
            "Dida365 batch completion finished after confirmation."
            if confirmed
            else "Dida365 batch completion finished."
        )
        lines = [
            header,
            f"- scope: {plan.operation_meta.get('scope_display', '(unknown)')}",
            f"- completed_count: {len(completed)}",
            f"- failed_count: {len(failed)}",
        ]
        if completed:
            lines.append("- completed_sample:")
            for item in completed[:5]:
                lines.append(
                    f"  - {self._display(item.title, fallback='(untitled)')} [{item.task_id}]"
                )
        if failed:
            lines.append("- failed_sample:")
            for item in failed[:3]:
                lines.append(f"  - {item}")
        return "\n".join(lines)

    async def _resolve_project(self, project_query: str) -> DidaProject:
        projects = await self.service.client.list_projects()
        if not projects:
            raise DidaValidationError("No Dida365 projects are available.")

        normalized_query = project_query.casefold()
        exact_matches = [
            project
            for project in projects
            if project.id.casefold() == normalized_query
            or project.name.casefold() == normalized_query
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            raise DidaValidationError(
                self._build_ambiguous_project_error(project_query, exact_matches)
            )

        partial_matches = [
            project
            for project in projects
            if normalized_query in project.id.casefold()
            or normalized_query in project.name.casefold()
        ]
        if len(partial_matches) == 1:
            return partial_matches[0]
        if not partial_matches:
            raise DidaValidationError(
                f"No Dida365 project matched '{project_query}'. Please use a more specific project name or identifier.",
            )
        raise DidaValidationError(
            self._build_ambiguous_project_error(project_query, partial_matches)
        )

    async def _resolve_task_reference(
        self,
        *,
        target_query: str,
        project_query: str,
        action: str,
    ) -> DidaMatchedTaskPlan:
        normalized_query = self._normalize_task_reference_query(target_query)
        if not normalized_query:
            raise DidaValidationError(
                f"The parsed Dida365 {action} intent is missing target_task_query.",
            )

        candidate_items = await self.service.list_unfinished_tasks()
        if not candidate_items:
            raise DidaValidationError(
                "No unfinished Dida365 tasks are available for matching."
            )

        filtered_items = self._filter_task_candidates_by_project(
            candidate_items, project_query
        )
        if not filtered_items:
            raise DidaValidationError(
                f"No unfinished Dida365 task matched '{normalized_query}' within the requested project scope.",
            )

        normalized_query_casefold = normalized_query.casefold()
        simplified_query = self._simplify_match_text(normalized_query)
        exact_matches = [
            item
            for item in filtered_items
            if item.task.id.casefold() == normalized_query_casefold
            or self._normalize_single_line(item.task.title).casefold()
            == normalized_query_casefold
            or (
                simplified_query
                and self._simplify_match_text(item.task.id) == simplified_query
            )
            or (
                simplified_query
                and self._simplify_match_text(item.task.title) == simplified_query
            )
        ]
        if len(exact_matches) == 1:
            return self._matched_task_from_item(exact_matches[0])
        if len(exact_matches) > 1:
            raise DidaValidationError(
                self._build_ambiguous_task_error(normalized_query, exact_matches)
            )
        partial_matches = [
            item
            for item in filtered_items
            if normalized_query_casefold in item.task.id.casefold()
            or normalized_query_casefold
            in self._normalize_single_line(item.task.title).casefold()
            or (
                simplified_query
                and simplified_query in self._simplify_match_text(item.task.id)
            )
            or (
                simplified_query
                and simplified_query in self._simplify_match_text(item.task.title)
            )
        ]
        if len(partial_matches) == 1:
            return self._matched_task_from_item(partial_matches[0])
        if partial_matches:
            raise DidaValidationError(
                self._build_ambiguous_task_error(normalized_query, partial_matches)
            )

        fuzzy_matches = self._rank_fuzzy_task_matches(normalized_query, filtered_items)
        if not fuzzy_matches:
            raise DidaValidationError(
                f"No unfinished Dida365 task matched '{normalized_query}'. Please use a more specific task title or identifier.",
            )
        top_score, top_item = fuzzy_matches[0]
        if len(fuzzy_matches) == 1:
            return self._matched_task_from_item(top_item)
        second_score = fuzzy_matches[1][0]
        if top_score >= 0.82 and (top_score - second_score) >= 0.08:
            return self._matched_task_from_item(top_item)
        ambiguous_items = [
            item for score, item in fuzzy_matches if (top_score - score) < 0.08
        ]
        raise DidaValidationError(
            self._build_ambiguous_task_error(normalized_query, ambiguous_items)
        )

    async def _resolve_batch_task_scope(
        self,
        *,
        batch_scope: str,
        project_query: str,
    ) -> tuple[list[DidaMatchedTaskPlan], str]:
        if batch_scope == "today":
            items = await self.service.list_today_tasks(today=self.service._today())
            scope_display = "today tasks"
        elif batch_scope == "overdue":
            items = [
                item
                for item in await self.service.list_unfinished_tasks()
                if self.service._is_overdue(item.task)
            ]
            scope_display = "overdue unfinished tasks"
        elif batch_scope == "unfinished_project":
            effective_project_query = self._normalize_single_line(
                project_query
            ) or self._normalize_single_line(self.settings.default_project)
            if not effective_project_query:
                raise DidaValidationError(
                    "batch_complete_tasks with unfinished_project scope requires an explicit project or configured default_project.",
                )
            project = await self._resolve_project(effective_project_query)
            items = [
                item
                for item in await self.service.list_unfinished_tasks()
                if item.project_id == project.id
            ]
            scope_display = f"unfinished tasks in project {project.name or project.id}"
        else:
            raise DidaValidationError(
                "Only these batch scopes are supported in this phase: today, overdue, unfinished_project.",
            )

        task_plans = [self._matched_task_from_item(item) for item in items]
        return task_plans, scope_display

    @staticmethod
    def _filter_task_candidates_by_project(
        items: list[DidaTaskWithProject],
        project_query: str,
    ) -> list[DidaTaskWithProject]:
        normalized_project_query = DidaTaskOpsCoordinator._normalize_single_line(
            project_query
        )
        if not normalized_project_query:
            return items
        query = normalized_project_query.casefold()
        exact_matches = [
            item
            for item in items
            if item.project_id.casefold() == query
            or item.project_name.casefold() == query
        ]
        if exact_matches:
            return exact_matches
        return [
            item
            for item in items
            if query in item.project_id.casefold()
            or query in item.project_name.casefold()
        ]

    def _matched_task_from_item(self, item: DidaTaskWithProject) -> DidaMatchedTaskPlan:
        return DidaMatchedTaskPlan(
            task_id=item.task.id,
            project_id=item.project_id,
            project_name=item.project_name,
            title=item.task.title,
            due_display=self.service._format_due(item.task),
            priority_display=self.service._format_priority(item.task),
            status_display=self.service._format_status(item.task),
        )

    def _rank_fuzzy_task_matches(
        self,
        query: str,
        items: list[DidaTaskWithProject],
    ) -> list[tuple[float, DidaTaskWithProject]]:
        simplified_query = self._simplify_match_text(query)
        if not simplified_query:
            return []
        scored_matches: list[tuple[float, DidaTaskWithProject]] = []
        for item in items:
            title_text = self._simplify_match_text(item.task.title)
            task_id_text = self._simplify_match_text(item.task.id)
            score = max(
                self._similarity_score(simplified_query, title_text),
                self._similarity_score(simplified_query, task_id_text),
            )
            if score >= 0.72:
                scored_matches.append((score, item))
        scored_matches.sort(
            key=lambda pair: (
                pair[0],
                -len(self._simplify_match_text(pair[1].task.title)),
                pair[1].task.title.casefold(),
            ),
            reverse=True,
        )
        return scored_matches

    @staticmethod
    def _similarity_score(query: str, candidate: str) -> float:
        if not query or not candidate:
            return 0.0
        if query == candidate:
            return 1.0
        if query in candidate:
            return 0.93
        if candidate in query:
            return 0.88
        return SequenceMatcher(None, query, candidate).ratio()

    @classmethod
    def _normalize_task_reference_query(cls, value: str) -> str:
        normalized = cls._normalize_single_line(value)
        if not normalized:
            return ""

        for _ in range(3):
            updated = cls._strip_wrapping_quotes(normalized)
            updated = cls._strip_task_reference_label(updated)
            updated = cls._strip_wrapping_quotes(updated)
            updated = cls._normalize_single_line(updated)
            if updated == normalized:
                break
            normalized = updated

        return normalized

    @staticmethod
    def _strip_wrapping_quotes(value: str) -> str:
        text = str(value or "").strip()
        quote_pairs = {
            '"': '"',
            "'": "'",
            "“": "”",
            "‘": "’",
            "「": "」",
            "『": "』",
            "《": "》",
            "（": "）",
            "(": ")",
        }
        while len(text) >= 2:
            closing = quote_pairs.get(text[0])
            if not closing or text[-1] != closing:
                break
            text = text[1:-1].strip()
        return text

    @classmethod
    def _strip_task_reference_label(cls, value: str) -> str:
        text = cls._normalize_single_line(value)
        if not text:
            return ""

        prefixes = (
            "task:",
            "task ",
            "task-",
            "task#",
            "任务:",
            "任务：",
            "任务 ",
            "待办:",
            "待办：",
            "todo:",
            "todo：",
            "todo ",
        )
        lowered = text.casefold()
        for prefix in prefixes:
            prefix_casefold = prefix.casefold()
            if lowered.startswith(prefix_casefold):
                candidate = text[len(prefix) :].strip()
                if candidate:
                    return candidate
        return text

    @classmethod
    def _simplify_match_text(cls, value: str) -> str:
        normalized = cls._normalize_single_line(value).casefold()
        return "".join(char for char in normalized if char.isalnum())

    def _build_ambiguous_project_error(
        self,
        project_query: str,
        projects: list[DidaProject],
    ) -> str:
        project_names = ", ".join(
            self._display(project.name or project.id, fallback="(unknown)")
            for project in projects[:5]
        )
        suffix = "" if len(projects) <= 5 else " ..."
        return (
            f"The project reference '{project_query}' matched multiple Dida365 projects. "
            f"Candidates: {project_names}{suffix}"
        )

    def _build_ambiguous_task_error(
        self,
        task_query: str,
        tasks: list[DidaTaskWithProject],
    ) -> str:
        lines = [
            (
                f"The task reference '{task_query}' matched multiple unfinished Dida365 tasks. "
                "Please rewrite the instruction with a more specific title, task ID, or project name."
            ),
            "Candidates:",
        ]
        for index, item in enumerate(tasks[:5], start=1):
            lines.append(self.service.format_task_candidate(item, index=index))
            if index < min(len(tasks), 5):
                lines.append("")
        if len(tasks) > 5:
            lines.extend(["", "..."])
        return "\n".join(lines)

    def _normalize_due_fields(
        self,
        *,
        due_datetime: str,
        due_date_value: str,
    ) -> tuple[str, str, bool, str, str]:
        normalized_due_datetime = self._normalize_single_line(due_datetime)
        normalized_due_date = self._normalize_single_line(due_date_value)
        time_zone = self._task_timezone_name()
        if normalized_due_datetime:
            parsed_dt = self._parse_due_datetime(normalized_due_datetime)
            return (
                self._format_api_datetime(parsed_dt),
                parsed_dt.strftime("%Y-%m-%d %H:%M"),
                False,
                time_zone,
                "",
            )
        if normalized_due_date:
            parsed_date = self._parse_due_date(normalized_due_date)
            parsed_start = datetime.combine(
                parsed_date, dt_time.min, tzinfo=self._task_timezone()
            )
            parsed_end = parsed_start + timedelta(days=1)
            return (
                self._format_api_datetime(parsed_end),
                parsed_date.isoformat(),
                True,
                time_zone,
                self._format_api_datetime(parsed_start),
            )
        return "", "(no due date)", False, "", ""

    def _normalize_update_fields(self, intent: DidaLlmTaskIntent) -> DidaUpdateTaskPlan:
        raw_update_fields = (
            intent.update_fields if isinstance(intent.update_fields, dict) else {}
        )
        merged_fields = dict(raw_update_fields)
        if "due_date" not in merged_fields and intent.due_date:
            merged_fields["due_date"] = intent.due_date
        if "due_datetime" not in merged_fields and intent.due_datetime:
            merged_fields["due_datetime"] = intent.due_datetime
        if "priority" not in merged_fields and intent.priority:
            merged_fields["priority"] = intent.priority
        if "content" not in merged_fields and intent.content:
            merged_fields["content"] = intent.content

        has_due_change = any(
            str(merged_fields.get(key, "") or "").strip()
            for key in ("due_date", "due_datetime")
        )
        due_value = ""
        due_display = "(unchanged)"
        is_all_day = False
        time_zone = ""
        start_value = ""
        if has_due_change:
            due_value, due_display, is_all_day, time_zone, start_value = (
                self._normalize_due_fields(
                    due_datetime=str(merged_fields.get("due_datetime", "") or ""),
                    due_date_value=str(merged_fields.get("due_date", "") or ""),
                )
            )

        has_priority_change = (
            "priority" in merged_fields
            and str(merged_fields.get("priority", "") or "").strip() != ""
        )
        priority = None
        priority_display = "(unchanged)"
        if has_priority_change:
            priority, priority_display = self._normalize_priority(
                str(merged_fields.get("priority", "") or "")
            )

        content_keys = ("content", "note", "description", "desc")
        has_content_change = any(key in merged_fields for key in content_keys)
        raw_content = ""
        for key in content_keys:
            if key in merged_fields:
                raw_content = str(merged_fields.get(key, "") or "")
                break
        content = self._normalize_multiline_text(raw_content)
        if has_content_change and not content:
            has_content_change = False

        if not has_due_change and not has_priority_change and not has_content_change:
            raise DidaValidationError(
                "The parsed Dida365 update_task intent did not include any supported update_fields. Supported fields are due_date, due_datetime, priority, and content.",
            )

        return DidaUpdateTaskPlan(
            has_due_change=has_due_change,
            due_value=due_value,
            due_display=due_display,
            is_all_day=is_all_day,
            time_zone=time_zone,
            start_value=start_value,
            has_priority_change=has_priority_change,
            priority=priority,
            priority_display=priority_display,
            has_content_change=has_content_change,
            content=content,
        )

    def _build_update_payload(
        self,
        *,
        current_task: DidaTask,
        target_task: DidaMatchedTaskPlan,
        update_plan: DidaUpdateTaskPlan,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = dict(current_task.raw or {})
        payload["id"] = current_task.id or target_task.task_id
        payload["projectId"] = current_task.project_id or target_task.project_id
        payload["title"] = current_task.title

        content_value = (
            update_plan.content
            if update_plan.has_content_change
            else current_task.content
        )
        payload["content"] = content_value
        if current_task.desc or "desc" in payload:
            payload["desc"] = current_task.desc

        if update_plan.has_priority_change:
            payload["priority"] = (
                0 if update_plan.priority is None else update_plan.priority
            )
        elif current_task.priority is not None or "priority" in payload:
            payload["priority"] = (
                0 if current_task.priority is None else current_task.priority
            )

        if update_plan.has_due_change:
            if update_plan.due_value:
                payload["dueDate"] = update_plan.due_value
                payload["isAllDay"] = update_plan.is_all_day
                if update_plan.start_value:
                    payload["startDate"] = update_plan.start_value
                else:
                    payload.pop("startDate", None)
                if update_plan.time_zone:
                    payload["timeZone"] = update_plan.time_zone
        elif current_task.due_date or "dueDate" in payload:
            payload["dueDate"] = current_task.due_date
            payload["isAllDay"] = current_task.is_all_day
            if current_task.start_date:
                payload["startDate"] = current_task.start_date
            else:
                payload.pop("startDate", None)
            time_zone = str(current_task.raw.get("timeZone", "") or "")
            if time_zone:
                payload["timeZone"] = time_zone

        return payload

    def _parse_due_datetime(self, value: str) -> datetime:
        normalized = value.strip().replace(" ", "T", 1).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise DidaValidationError(
                f"The parsed due_datetime '{value}' is not a supported date-time format.",
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self._task_timezone())
        return parsed

    @staticmethod
    def _parse_due_date(value: str) -> date:
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise DidaValidationError(
                f"The parsed due_date '{value}' is not a supported YYYY-MM-DD date.",
            ) from exc

    def _task_timezone(self):
        return get_timezone(self._task_timezone_name())

    def _task_timezone_name(self) -> str:
        return self.settings.timezone

    @staticmethod
    def _format_api_datetime(value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%S%z")

    @staticmethod
    def _normalize_priority(value: str) -> tuple[int | None, str]:
        text = str(value or "").strip().lower()
        if not text or text == "none":
            return None, "none"
        priority_map = {
            "0": (0, "none"),
            "1": (1, "low"),
            "3": (3, "medium"),
            "5": (5, "high"),
            "low": (1, "low"),
            "medium": (3, "medium"),
            "high": (5, "high"),
        }
        if text not in priority_map:
            raise DidaValidationError(
                f"The parsed priority '{value}' is not supported. Use none, low, medium, or high.",
            )
        return priority_map[text]

    def _compute_confirmation_policy(
        self,
        *,
        risk_level: str,
        intent: DidaLlmTaskIntent,
    ) -> tuple[bool, str]:
        reasons: list[str] = []
        if risk_level in {"low", "medium"} and self.settings.confirm_low_risk_writes:
            reasons.append("confirm_low_risk_writes is enabled")
        if risk_level == "high" and self.settings.confirm_high_risk_writes:
            reasons.append("confirm_high_risk_writes is enabled")
        if intent.confidence is not None and intent.confidence < 0.65:
            reasons.append("LLM confidence is low")
        if intent.ambiguity_reason:
            reasons.append("LLM reported ambiguity")
        return bool(reasons), "; ".join(reasons) or "not required"

    @staticmethod
    def _resolve_risk_level(action: str) -> str:
        if action in {"create_task", "complete_task", "update_task"}:
            return "low"
        return "high"

    async def _store_pending_confirmation(self, event, plan: DidaExecutionPlan) -> None:
        now = time.time()
        plan.created_at_ts = now
        plan.expires_at_ts = now + float(self.settings.confirmation_timeout_seconds)
        await self._put_kv_data(self._pending_key(event), plan.to_dict())

    async def _load_pending_confirmation(self, event) -> DidaExecutionPlan | None:
        data = await self._get_kv_data(self._pending_key(event), None)
        if not data:
            return None
        if not isinstance(data, dict):
            await self._delete_kv_data(self._pending_key(event))
            raise DidaConfirmationError(
                "Stored Dida365 confirmation data is invalid and has been cleared.",
            )
        return DidaExecutionPlan.from_dict(data)

    def _pending_key(self, event) -> str:
        sender_id = str(getattr(event, "get_sender_id", lambda: "")() or "session")
        return (
            f"{self.PENDING_CONFIRMATION_PREFIX}:{event.unified_msg_origin}:{sender_id}"
        )

    def _render_confirmation_request(self, plan: DidaExecutionPlan) -> str:
        seconds_left = max(0, int(plan.expires_at_ts - time.time()))
        lines = [
            "Dida365 task operation is waiting for confirmation.",
            f"- action: {plan.action}",
            f"- risk_level: {plan.risk_level}",
            (
                f"- confirmation_reason: {plan.confirmation_reason}"
                if plan.confirmation_reason
                else "- confirmation_reason: (none)"
            ),
        ]
        if plan.action == "create_task" and plan.create_task:
            lines.extend(
                [
                    f"- title: {self._display(plan.create_task.title, fallback='(untitled)')}",
                    f"- project: {self._display(plan.create_task.project_name, fallback=plan.create_task.project_id)}",
                    f"- due: {plan.create_task.due_display}",
                    f"- priority: {plan.create_task.priority_display}",
                ]
            )
        elif plan.action == "move_task" and plan.target_task:
            lines.extend(
                [
                    f"- title: {self._display(plan.target_task.title, fallback='(untitled)')}",
                    f"- from_project: {self._display(plan.target_task.project_name, fallback=plan.target_task.project_id)}",
                    f"- to_project: {self._display(str(plan.operation_meta.get('target_project_name', '')), fallback=str(plan.operation_meta.get('target_project_id', '(unknown)')))}",
                    f"- due: {plan.target_task.due_display}",
                    f"- task_id: {plan.target_task.task_id}",
                ]
            )
        elif plan.action == "delete_task" and plan.target_task:
            lines.extend(
                [
                    f"- title: {self._display(plan.target_task.title, fallback='(untitled)')}",
                    f"- project: {self._display(plan.target_task.project_name, fallback=plan.target_task.project_id)}",
                    f"- due: {plan.target_task.due_display}",
                    f"- task_id: {plan.target_task.task_id}",
                ]
            )
        elif plan.action == "batch_complete_tasks":
            lines.extend(
                [
                    f"- scope: {plan.operation_meta.get('scope_display', '(unknown)')}",
                    f"- task_count: {len(plan.operation_meta.get('tasks') or [])}",
                    "- sample:",
                ]
            )
            for item in (plan.operation_meta.get("tasks") or [])[:5]:
                if isinstance(item, dict):
                    task_plan = DidaMatchedTaskPlan.from_dict(item)
                    lines.append(
                        f"  - {self._display(task_plan.title, fallback='(untitled)')} [{task_plan.task_id}]"
                    )
        elif plan.target_task:
            lines.extend(
                [
                    f"- title: {self._display(plan.target_task.title, fallback='(untitled)')}",
                    f"- project: {self._display(plan.target_task.project_name, fallback=plan.target_task.project_id)}",
                    f"- due: {plan.target_task.due_display}",
                    f"- status: {plan.target_task.status_display}",
                    f"- task_id: {plan.target_task.task_id}",
                ]
            )
            if plan.action == "update_task" and plan.update_task:
                lines.append(
                    f"- updated_fields: {self._describe_updated_fields(plan.update_task)}"
                )
        lines.extend(
            [
                f"- expires_in_seconds: {seconds_left}",
                "Reply with /dida_confirm to execute, or /dida_cancel to discard.",
            ]
        )
        return "\n".join(lines)

    def _resolve_due_feedback(
        self,
        *,
        requested_due: str,
        requested_display: str,
        effective_task: DidaTask,
    ) -> tuple[str, str]:
        if effective_task.due_date:
            return self.service._format_due(effective_task), ""
        if requested_due:
            return (
                requested_display,
                "requested due date was not returned by Dida after execution; the server may have ignored it",
            )
        return "(no due date)", ""

    @staticmethod
    def _normalize_single_line(value: str) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        text = " ".join(part.strip() for part in text.splitlines() if part.strip())
        return " ".join(text.split())

    @staticmethod
    def _normalize_multiline_text(value: str) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines)

    def _display(self, value: str, *, fallback: str) -> str:
        return self.service._format_display_text(value, fallback=fallback)

    def _plan_subject(self, plan: DidaExecutionPlan) -> str:
        if plan.create_task:
            return self._display(plan.create_task.title, fallback="(untitled)")
        if plan.target_task:
            return self._display(plan.target_task.title, fallback="(untitled)")
        if plan.action == "batch_complete_tasks":
            return f"{len(plan.operation_meta.get('tasks') or [])} tasks"
        return "(unknown)"

    @staticmethod
    def _describe_updated_fields(update_plan: DidaUpdateTaskPlan) -> str:
        fields: list[str] = []
        if update_plan.has_due_change:
            fields.append(f"due={update_plan.due_display}")
        if update_plan.has_priority_change:
            fields.append(f"priority={update_plan.priority_display}")
        if update_plan.has_content_change:
            fields.append("content")
        return ", ".join(fields) or "(none)"
