from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta

from .client import DidaClient
from .exceptions import (
    DidaApiError,
    DidaConfigurationError,
    DidaError,
    DidaNetworkError,
)
from .time_utils import (
    get_timezone,
    now_in_timezone,
    parse_api_datetime,
    today_in_timezone,
)
from .types import (
    DidaPluginSettings,
    DidaReportTaskView,
    DidaStructuredReport,
    DidaTask,
    DidaTaskWithProject,
)

_MARKDOWN_ESCAPE_PATTERN = re.compile(r"([\\`*_{}\[\]()#+!|>])")


class DidaService:
    """Application service boundary for future Dida365 features."""

    TODAY_DISPLAY_LIMIT = 20
    UNFINISHED_DISPLAY_LIMIT = 30

    def __init__(
        self,
        settings: DidaPluginSettings,
        *,
        client: DidaClient | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or DidaClient(settings)

    def build_status_summary(self) -> str:
        return (
            "滴答清单插件已加载\n"
            f"- 已配置访问令牌: {bool(self.settings.access_token.strip())}\n"
            f"- 已配置 API 地址: {bool(self.settings.api_base_url.strip())}\n"
            f"- 已配置默认项目: {bool(self.settings.default_project.strip())}\n"
            f"- 时区: {self.settings.timezone}\n"
            f"- 已开启主动汇报: {self.settings.enable_daily_briefing}\n"
            f"- 已开启自然语言任务操作: {self.settings.enable_llm_task_ops}\n"
            "- Access Token 有效期提示: 通常约 180 天\n"
            "- 自动刷新 Access Token: 未启用，请手动更新"
        )

    async def probe_read_access(self) -> str:
        projects = await self.client.list_projects()
        if not projects:
            return "滴答清单 API 调用成功，但没有返回任何项目。"
        project_names = ", ".join(
            self._format_display_text(
                project.name or project.id,
                fallback="(unnamed)",
            )
            for project in projects[:5]
        )
        suffix = "" if len(projects) <= 5 else " ..."
        return (
            f"滴答清单 API 读取探测成功。\n"
            f"- 项目数量: {len(projects)}\n"
            f"- 示例项目: {project_names}{suffix}"
        )

    async def list_projects_summary(self) -> str:
        projects = await self.client.list_projects()
        if not projects:
            return "没有读取到任何滴答清单项目。"
        lines = [f"滴答清单项目数: {len(projects)}"]
        for project in projects[:10]:
            project_name = self._format_display_text(
                project.name,
                fallback="(unnamed)",
            )
            project_id = self._format_display_text(project.id, fallback="(unknown)")
            lines.append(f"- {project_name} [{project_id}]")
        if len(projects) > 10:
            lines.append("- ...")
        return "\n".join(lines)

    async def get_project_data_summary(self, project_id: str) -> str:
        project_data = await self.client.get_project_data(project_id)
        project_name = (
            project_data.project.name
            if project_data.project and project_data.project.name
            else project_id
        )
        return (
            f"已读取滴答清单项目数据。\n"
            f"- 项目: {self._format_display_text(project_name, fallback='(未知项目)')}\n"
            f"- 任务数: {len(project_data.tasks)}"
        )

    async def list_today_tasks_summary(self) -> str:
        today = self._today()
        today_tasks = await self.list_today_tasks(today=today)
        if not today_tasks:
            return f"今天没有到期任务（{today.isoformat()}）。"

        lines = [f"今日到期任务（{today.isoformat()}）: {len(today_tasks)}"]
        task_blocks = [
            self._format_task_block_from_item(item)
            for item in today_tasks[: self.TODAY_DISPLAY_LIMIT]
        ]
        if task_blocks:
            lines.append("")
            lines.extend(task_blocks)
        if len(today_tasks) > self.TODAY_DISPLAY_LIMIT:
            lines.extend(["", "..."])
        return "\n\n".join(lines)

    async def list_today_tasks(self, *, today: date) -> list[DidaTaskWithProject]:
        tasks = await self._collect_all_task_items()
        today_tasks = [
            item
            for item in tasks
            if self._is_task_due_today(item.task, today=today)
            and not self._is_completed(item.task)
        ]
        today_tasks.sort(
            key=lambda item: (
                self._sort_due_value(item.task),
                item.project_name,
                item.task.title,
            ),
        )
        return today_tasks

    async def list_unfinished_tasks_summary(self) -> str:
        unfinished_tasks = await self.list_unfinished_tasks()
        if not unfinished_tasks:
            return "没有未完成任务。"

        overdue_count = sum(
            1 for item in unfinished_tasks if self._is_overdue(item.task)
        )
        no_due_count = sum(
            1
            for item in unfinished_tasks
            if not self._effective_due_datetime(item.task)
        )

        lines = [
            f"未完成任务数: {len(unfinished_tasks)}",
            f"- 逾期任务: {overdue_count}",
            f"- 无截止日期: {no_due_count}",
            "- 当前展示: 按紧急程度排序的前 30 条",
        ]
        task_blocks = [
            self._format_task_block_from_item(item, include_overdue=True)
            for item in unfinished_tasks[: self.UNFINISHED_DISPLAY_LIMIT]
        ]
        if task_blocks:
            lines.append("")
            lines.extend(task_blocks)
        if len(unfinished_tasks) > self.UNFINISHED_DISPLAY_LIMIT:
            remaining = len(unfinished_tasks) - self.UNFINISHED_DISPLAY_LIMIT
            lines.extend(["", f"... 还有 {remaining} 条未完成任务未展示"])
        return "\n\n".join(lines)

    async def list_unfinished_tasks(self) -> list[DidaTaskWithProject]:
        tasks = await self._collect_all_task_items()
        unfinished_tasks = [item for item in tasks if not self._is_completed(item.task)]
        unfinished_tasks.sort(
            key=lambda item: (
                self._unfinished_sort_bucket(item.task),
                self._sort_due_value(item.task),
                -self._priority_rank(item.task),
                item.project_name,
                item.task.title,
            ),
        )
        return unfinished_tasks

    async def build_today_report(
        self,
        *,
        now: datetime,
        include_overdue: bool,
        max_tasks: int | None = None,
    ) -> DidaStructuredReport:
        all_items = await self._collect_all_task_items()
        now = self._normalize_now(now)
        today_value = now.date()
        selected_items = [
            item
            for item in all_items
            if self._should_include_in_today_report(
                item.task,
                today=today_value,
                include_overdue=include_overdue,
            )
        ]
        selected_items.sort(
            key=lambda item: (
                self._today_report_sort_bucket(item.task, today=today_value),
                self._sort_due_value(item.task),
                item.project_name,
                item.task.title,
            ),
        )

        total_count = len(selected_items)
        report_tasks = [self._make_report_task_view(item) for item in selected_items]
        overdue_count = sum(1 for item in selected_items if self._is_overdue(item.task))
        due_today_count = sum(
            1
            for item in selected_items
            if self._is_task_due_today(item.task, today=today_value)
        )
        truncated_count = 0
        if max_tasks is not None and len(report_tasks) > max_tasks:
            truncated_count = len(report_tasks) - max_tasks
            report_tasks = report_tasks[:max_tasks]

        selection_rule = "今天到期且未完成的任务"
        sorting_rule = "按截止时间升序"
        if include_overdue:
            selection_rule = "今天到期或已经逾期且未完成的任务"
            sorting_rule = "逾期优先，其次按截止时间升序"

        return DidaStructuredReport(
            report_type="today",
            current_time=now.strftime("%Y-%m-%d %H:%M"),
            selection_rule=selection_rule,
            sorting_rule=sorting_rule,
            summary_counts={
                "overdue_count": overdue_count,
                "due_today_count": due_today_count,
                "no_due_date_count": 0,
            },
            tasks=report_tasks,
            total_task_count=total_count,
            truncated_task_count=truncated_count,
        )

    async def build_unfinished_report(
        self,
        *,
        now: datetime,
        max_tasks: int | None = None,
    ) -> DidaStructuredReport:
        now = self._normalize_now(now)
        selected_items = await self.list_unfinished_tasks()
        total_count = len(selected_items)
        report_tasks = [self._make_report_task_view(item) for item in selected_items]
        overdue_count = sum(1 for item in selected_items if self._is_overdue(item.task))
        no_due_date_count = sum(
            1 for item in selected_items if not self._effective_due_datetime(item.task)
        )
        truncated_count = 0
        if max_tasks is not None and len(report_tasks) > max_tasks:
            truncated_count = len(report_tasks) - max_tasks
            report_tasks = report_tasks[:max_tasks]

        return DidaStructuredReport(
            report_type="unfinished",
            current_time=now.strftime("%Y-%m-%d %H:%M"),
            selection_rule="所有未完成任务，包含没有截止日期的任务",
            sorting_rule="逾期优先，其次按截止时间升序，再显示无截止日期任务，同一紧急度下高优先级优先",
            summary_counts={
                "overdue_count": overdue_count,
                "due_today_count": sum(
                    1
                    for item in selected_items
                    if self._is_task_due_today(item.task, today=now.date())
                ),
                "no_due_date_count": no_due_date_count,
            },
            tasks=report_tasks,
            total_task_count=total_count,
            truncated_task_count=truncated_count,
        )

    def render_direct_report(self, report: DidaStructuredReport) -> str:
        title = "滴答清单定时汇报：今日任务"
        if report.report_type == "unfinished":
            title = "滴答清单定时汇报：未完成任务"

        lines = [
            title,
            f"生成时间: {report.current_time}",
            f"筛选规则: {report.selection_rule}",
            f"排序规则: {report.sorting_rule}",
            f"任务总数: {report.total_task_count}",
            f"逾期任务: {report.summary_counts.get('overdue_count', 0)}",
            f"今日到期: {report.summary_counts.get('due_today_count', 0)}",
            f"无截止日期: {report.summary_counts.get('no_due_date_count', 0)}",
        ]
        if not report.tasks:
            lines.extend(["", "没有任务符合本次汇报条件。"])
            return "\n".join(lines)

        task_blocks = []
        for index, task in enumerate(report.tasks, start=1):
            task_blocks.append(self._format_task_block_from_view(task, index=index))
        lines.append("")
        lines.append("\n\n".join(task_blocks))
        if report.truncated_task_count:
            lines.extend(
                [
                    "",
                    f"... 还有 {report.truncated_task_count} 条任务未在本次汇报中展开。",
                ]
            )
        return "\n".join(lines)

    def build_structured_report_input(self, report: DidaStructuredReport) -> str:
        lines = [
            "[REPORT_META]",
            f"report_type: {report.report_type}",
            f"current_time: {report.current_time}",
            f"selection_rule: {report.selection_rule}",
            f"sorting_rule: {report.sorting_rule}",
            f"task_count: {report.total_task_count}",
            "",
            "[SUMMARY]",
            f"overdue_count: {report.summary_counts.get('overdue_count', 0)}",
            f"due_today_count: {report.summary_counts.get('due_today_count', 0)}",
            f"no_due_date_count: {report.summary_counts.get('no_due_date_count', 0)}",
        ]
        if report.truncated_task_count:
            lines.append(f"truncated_task_count: {report.truncated_task_count}")
        lines.extend(["", "[TASKS]"])
        if not report.tasks:
            lines.append("none")
            return "\n".join(lines)

        for index, task in enumerate(report.tasks, start=1):
            lines.extend(
                [
                    f"{index}.",
                    f"title: {task.title}",
                    f"project: {task.project}",
                    f"due: {task.due}",
                    f"priority: {task.priority}",
                    f"status: {task.status}",
                    f"overdue: {'true' if task.overdue else 'false'}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    async def _collect_all_task_items(self) -> list[DidaTaskWithProject]:
        projects = await self.client.list_projects()
        if not projects:
            return []

        project_results = await asyncio.gather(
            *[
                self.client.get_project_data(project.id)
                for project in projects
                if project.id
            ],
            return_exceptions=True,
        )

        successful_results = []
        for result in project_results:
            if isinstance(result, Exception):
                continue
            successful_results.append(result)

        if not successful_results and project_results:
            first_error = project_results[0]
            if isinstance(first_error, Exception):
                raise first_error

        task_items: list[DidaTaskWithProject] = []
        for project_data in successful_results:
            project = project_data.project
            project_name = (
                project.name
                if project and project.name
                else project.id
                if project
                else ""
            )
            project_id = project.id if project else ""
            for task in project_data.tasks:
                task_items.append(
                    DidaTaskWithProject(
                        project_id=project_id or task.project_id,
                        project_name=project_name or task.project_id,
                        task=task,
                    )
                )
        return task_items

    def _timezone_name(self) -> str:
        return self.settings.timezone

    def _timezone(self):
        return get_timezone(self._timezone_name())

    def _normalize_now(self, value: datetime | None = None) -> datetime:
        current = value or now_in_timezone(self._timezone_name())
        if current.tzinfo is None:
            return current.replace(tzinfo=self._timezone())
        return current.astimezone(self._timezone())

    def _today(self) -> date:
        return today_in_timezone(self._timezone_name())

    def _parse_datetime(
        self, value: str, *, task: DidaTask | None = None
    ) -> datetime | None:
        assume_timezone_name = (
            task.time_zone if task and task.time_zone else self._timezone_name()
        )
        return parse_api_datetime(
            value,
            assume_timezone_name=assume_timezone_name,
            target_timezone_name=self._timezone_name(),
        )

    @staticmethod
    def _is_completed(task: DidaTask) -> bool:
        if task.completed_time:
            return True
        return task.status == 2

    def _effective_due_datetime(self, task: DidaTask) -> datetime | None:
        if task.is_all_day:
            start_dt = self._parse_datetime(task.start_date, task=task)
            if start_dt:
                return start_dt
            due_dt = self._parse_datetime(task.due_date, task=task)
            if due_dt:
                return due_dt - timedelta(days=1)
            return None
        return self._parse_datetime(task.due_date, task=task)

    def _is_task_due_today(self, task: DidaTask, *, today: date) -> bool:
        due_dt = self._effective_due_datetime(task)
        if not due_dt:
            return False
        return due_dt.date() == today

    def _is_overdue(self, task: DidaTask, *, today: date | None = None) -> bool:
        if self._is_completed(task):
            return False
        due_dt = self._effective_due_datetime(task)
        if not due_dt:
            return False
        today_value = today or self._today()
        return due_dt.date() < today_value

    def _sort_due_value(self, task: DidaTask) -> tuple[int, str]:
        due_dt = self._effective_due_datetime(task)
        if not due_dt:
            return (1, "")
        return (0, due_dt.isoformat())

    def _unfinished_sort_bucket(self, task: DidaTask) -> int:
        if self._is_overdue(task):
            return 0
        if self._effective_due_datetime(task):
            return 1
        return 2

    def _format_due(self, task: DidaTask) -> str:
        due_dt = self._effective_due_datetime(task)
        if not due_dt:
            return "(无截止日期)"
        if task.is_all_day:
            return due_dt.date().isoformat()
        return due_dt.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _format_priority(task: DidaTask) -> str:
        priority_map = {
            None: "(未知)",
            0: "none",
            1: "low",
            3: "medium",
            5: "high",
        }
        return priority_map.get(task.priority, str(task.priority))

    @classmethod
    def _format_status(cls, task: DidaTask) -> str:
        if cls._is_completed(task):
            return "completed"
        status_map = {
            None: "open",
            0: "open",
            1: "in_progress",
            2: "completed",
        }
        return status_map.get(task.status, str(task.status))

    @staticmethod
    def _priority_rank(task: DidaTask) -> int:
        return task.priority or 0

    @staticmethod
    def _escape_markdown(value: str) -> str:
        return _MARKDOWN_ESCAPE_PATTERN.sub(r"\\\1", value)

    @staticmethod
    def _normalize_text(value: str, *, fallback: str) -> str:
        normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("\n", " / ").strip()
        if not normalized:
            return fallback
        return normalized

    @classmethod
    def _format_display_text(
        cls,
        value: str,
        *,
        fallback: str,
    ) -> str:
        normalized = cls._normalize_text(value, fallback=fallback)
        if normalized == fallback:
            return fallback
        return cls._escape_markdown(normalized)

    def _make_report_task_view(self, item: DidaTaskWithProject) -> DidaReportTaskView:
        return DidaReportTaskView(
            title=self._normalize_text(item.task.title, fallback="(无标题)"),
            project=self._normalize_text(
                item.project_name or item.project_id,
                fallback="(未知项目)",
            ),
            due=self._format_due(item.task),
            priority=self._format_priority(item.task),
            status=self._format_status(item.task),
            overdue=self._is_overdue(item.task),
        )

    def format_task_candidate(
        self,
        item: DidaTaskWithProject,
        *,
        index: int | None = None,
    ) -> str:
        title = self._format_display_text(item.task.title, fallback="(无标题)")
        project = self._format_display_text(
            item.project_name or item.project_id,
            fallback="(未知项目)",
        )
        task_id = self._format_display_text(item.task.id, fallback="(未知)")
        prefix = f"{index}. " if index is not None else ""
        return "\n".join(
            [
                f"{prefix}任务: {title}",
                f"项目: {project}",
                f"截止: {self._format_due(item.task)}",
                f"优先级: {self._format_priority(item.task)}",
                f"状态: {self._format_status(item.task)}",
                f"任务 ID: {task_id}",
            ]
        )

    def _format_task_block_from_item(
        self,
        item: DidaTaskWithProject,
        *,
        include_overdue: bool = False,
    ) -> str:
        return self._format_task_block_from_view(
            self._make_report_task_view(item),
            include_overdue=include_overdue,
        )

    @classmethod
    def _format_task_block_from_view(
        cls,
        task: DidaReportTaskView,
        *,
        index: int | None = None,
        include_overdue: bool = True,
    ) -> str:
        title = cls._escape_markdown(task.title)
        project = cls._escape_markdown(task.project)
        header = f"任务 {index}: {title}  " if index else f"任务: {title}  "
        lines = [
            header,
            f"项目: {project}  ",
            f"截止: {task.due}  ",
            f"优先级: {task.priority}  ",
            f"状态: {task.status}",
        ]
        if include_overdue:
            lines.append(f"是否逾期: {'是' if task.overdue else '否'}")
        return "\n".join(lines)

    def _should_include_in_today_report(
        self,
        task: DidaTask,
        *,
        today: date,
        include_overdue: bool,
    ) -> bool:
        if self._is_completed(task):
            return False
        due_dt = self._effective_due_datetime(task)
        if not due_dt:
            return False
        if include_overdue:
            return due_dt.date() <= today
        return due_dt.date() == today

    def _today_report_sort_bucket(self, task: DidaTask, *, today: date) -> int:
        due_dt = self._effective_due_datetime(task)
        if not due_dt:
            return 2
        if due_dt.date() < today:
            return 0
        return 1

    @staticmethod
    def explain_error(error: Exception) -> str:
        if isinstance(error, DidaConfigurationError):
            return str(error)
        if isinstance(error, DidaNetworkError):
            return str(error)
        if isinstance(error, DidaApiError):
            return str(error)
        if isinstance(error, DidaError):
            return str(error)
        return f"滴答清单插件发生未预期错误：{error!s}"
