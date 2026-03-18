from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astrbot.core.config.astrbot_config import AstrBotConfig

from .time_utils import resolve_timezone_name


@dataclass(slots=True)
class DidaPluginSettings:
    access_token: str
    api_base_url: str
    default_project: str
    request_timeout_seconds: int
    timezone: str
    enable_daily_briefing: bool
    morning_report_time: str
    evening_report_time: str
    report_target: str
    enable_today_report: bool
    enable_unfinished_report: bool
    report_mode: str
    llm_report_prompt: str
    llm_max_tasks: int
    include_overdue_in_today_report: bool
    enable_llm_task_ops: bool
    llm_task_ops_prompt: str
    confirm_low_risk_writes: bool
    confirm_high_risk_writes: bool
    confirmation_timeout_seconds: int

    @classmethod
    def from_config(
        cls,
        config: AstrBotConfig,
        *,
        fallback_timezone: str = "Asia/Shanghai",
    ) -> DidaPluginSettings:
        report_mode = str(config.get("report_mode", "direct") or "direct").lower()
        if report_mode not in {"direct", "llm"}:
            report_mode = "direct"

        return cls(
            access_token=str(config.get("access_token", "") or ""),
            api_base_url=str(config.get("api_base_url", "") or ""),
            default_project=str(config.get("default_project", "") or ""),
            request_timeout_seconds=max(
                1,
                int(config.get("request_timeout_seconds", 15) or 15),
            ),
            timezone=resolve_timezone_name(
                str(config.get("timezone", "") or ""),
                fallback_timezone=fallback_timezone,
            ),
            enable_daily_briefing=cls._to_bool(
                config.get("enable_daily_briefing", False),
            ),
            morning_report_time=str(config.get("morning_report_time", "09:00") or ""),
            evening_report_time=str(config.get("evening_report_time", "18:00") or ""),
            report_target=str(config.get("report_target", "") or ""),
            enable_today_report=cls._to_bool(
                config.get("enable_today_report", True),
            ),
            enable_unfinished_report=cls._to_bool(
                config.get("enable_unfinished_report", True),
            ),
            report_mode=report_mode,
            llm_report_prompt=str(config.get("llm_report_prompt", "") or ""),
            llm_max_tasks=max(1, int(config.get("llm_max_tasks", 12) or 12)),
            include_overdue_in_today_report=cls._to_bool(
                config.get("include_overdue_in_today_report", False),
            ),
            enable_llm_task_ops=cls._to_bool(
                config.get("enable_llm_task_ops", True),
            ),
            llm_task_ops_prompt=str(config.get("llm_task_ops_prompt", "") or ""),
            confirm_low_risk_writes=cls._to_bool(
                config.get("confirm_low_risk_writes", False),
            ),
            confirm_high_risk_writes=cls._to_bool(
                config.get("confirm_high_risk_writes", True),
            ),
            confirmation_timeout_seconds=max(
                30,
                int(config.get("confirmation_timeout_seconds", 180) or 180),
            ),
        )

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)


@dataclass(slots=True)
class DidaProject:
    id: str
    name: str
    kind: str = ""
    color: str = ""
    view_mode: str = ""
    closed: bool = False
    group_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DidaProject:
        return cls(
            id=str(data.get("id", "") or ""),
            name=str(data.get("name", "") or ""),
            kind=str(data.get("kind", "") or ""),
            color=str(data.get("color", "") or ""),
            view_mode=str(data.get("viewMode", "") or ""),
            closed=bool(data.get("closed", False)),
            group_id=str(data.get("groupId", "") or ""),
            raw=data,
        )


@dataclass(slots=True)
class DidaTask:
    id: str
    project_id: str
    title: str
    content: str = ""
    desc: str = ""
    status: int | None = None
    priority: int | None = None
    due_date: str = ""
    start_date: str = ""
    completed_time: str = ""
    is_all_day: bool = False
    time_zone: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DidaTask:
        return cls(
            id=str(data.get("id", "") or ""),
            project_id=str(data.get("projectId", "") or ""),
            title=str(data.get("title", "") or ""),
            content=str(data.get("content", "") or ""),
            desc=str(data.get("desc", "") or ""),
            status=cls._to_optional_int(data.get("status")),
            priority=cls._to_optional_int(data.get("priority")),
            due_date=str(data.get("dueDate", "") or ""),
            start_date=str(data.get("startDate", "") or ""),
            completed_time=str(data.get("completedTime", "") or ""),
            is_all_day=bool(data.get("isAllDay", False)),
            time_zone=str(data.get("timeZone", "") or ""),
            raw=data,
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
class DidaProjectData:
    project: DidaProject | None
    tasks: list[DidaTask]
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DidaProjectData:
        project_data = data.get("project")
        project = (
            DidaProject.from_api(project_data)
            if isinstance(project_data, dict)
            else None
        )
        tasks_data = data.get("tasks", [])
        tasks = [
            DidaTask.from_api(task) for task in tasks_data if isinstance(task, dict)
        ]
        return cls(project=project, tasks=tasks, raw=data)


@dataclass(slots=True)
class DidaTaskWithProject:
    project_id: str
    project_name: str
    task: DidaTask


@dataclass(slots=True)
class DidaReportTaskView:
    title: str
    project: str
    due: str
    priority: str
    status: str
    overdue: bool


@dataclass(slots=True)
class DidaStructuredReport:
    report_type: str
    current_time: str
    selection_rule: str
    sorting_rule: str
    summary_counts: dict[str, int]
    tasks: list[DidaReportTaskView]
    total_task_count: int
    truncated_task_count: int = 0
