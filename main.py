from __future__ import annotations

from collections.abc import Awaitable, Callable

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.message.message_event_result import MessageChain

from .client import DidaClient
from .llm_ops import _DEFAULT_LLM_TASK_OPS_PROMPT
from .reporting import DidaReportingCoordinator
from .service import DidaService
from .task_ops import DidaTaskOpsCoordinator
from .types import DidaPluginSettings


class Main(Star):
    """Dida365 AstrBot plugin."""

    REPORT_TARGET_KV_KEY = "report_target_umo"
    REPORT_JOB_NAME_PREFIX = "dida365_report"

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context, config)
        self.config = config
        self._http_session: aiohttp.ClientSession | None = None

    async def initialize(self) -> None:
        self._ensure_visible_prompt_defaults()
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(trust_env=True)
        await self._sync_report_jobs()

    async def terminate(self) -> None:
        await self._clear_report_jobs()
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None

    def _build_settings(self) -> DidaPluginSettings:
        fallback_timezone = str(
            self.context.get_config().get("timezone", "Asia/Shanghai")
            or "Asia/Shanghai"
        )
        return DidaPluginSettings.from_config(
            self.config,
            fallback_timezone=fallback_timezone,
        )

    def _build_client(self, settings: DidaPluginSettings | None = None) -> DidaClient:
        effective_settings = settings or self._build_settings()
        return DidaClient(effective_settings, session=self._http_session)

    def _build_service(self) -> DidaService:
        settings = self._build_settings()
        return DidaService(settings, client=self._build_client(settings))

    def _build_reporting(self) -> DidaReportingCoordinator:
        settings = self._build_settings()
        service = DidaService(settings, client=self._build_client(settings))
        return DidaReportingCoordinator(self.context, settings, service)

    def _build_task_ops(self) -> DidaTaskOpsCoordinator:
        settings = self._build_settings()
        service = DidaService(settings, client=self._build_client(settings))
        return DidaTaskOpsCoordinator(
            self.context,
            settings,
            service,
            get_kv_data=self.get_kv_data,
            put_kv_data=self.put_kv_data,
            delete_kv_data=self.delete_kv_data,
        )

    def _plugin_store_id(self) -> str:
        return getattr(self, "plugin_id", "astrbot_plugin_dida365")

    def _ensure_visible_prompt_defaults(self) -> None:
        llm_task_ops_prompt = str(self.config.get("llm_task_ops_prompt", "") or "")
        if llm_task_ops_prompt.strip():
            return
        self.config["llm_task_ops_prompt"] = _DEFAULT_LLM_TASK_OPS_PROMPT
        self.config.save_config()

    async def _get_bound_report_target(self) -> str:
        value = await self.get_kv_data(self.REPORT_TARGET_KV_KEY, "")
        return str(value or "")

    async def _get_effective_report_target(self) -> str:
        bound_target = await self._get_bound_report_target()
        if bound_target:
            return bound_target
        return self._build_settings().report_target

    def _job_name(self, report_type: str) -> str:
        return f"{self.REPORT_JOB_NAME_PREFIX}:{self._plugin_store_id()}:{report_type}"

    async def _list_report_jobs(self):
        jobs = await self.context.cron_manager.list_jobs(job_type="basic")
        prefix = f"{self.REPORT_JOB_NAME_PREFIX}:{self._plugin_store_id()}:"
        return [job for job in jobs if job.name.startswith(prefix)]

    async def _clear_report_jobs(self) -> None:
        for job in await self._list_report_jobs():
            await self.context.cron_manager.delete_job(job.job_id)

    async def _sync_report_jobs(self) -> None:
        await self._clear_report_jobs()

        settings = self._build_settings()
        if not settings.enable_daily_briefing:
            return

        target_umo = await self._get_effective_report_target()
        if not target_umo:
            logger.info(
                "Dida365 daily briefing is enabled but no report target is bound.",
            )
            return

        reporting = self._build_reporting()
        timezone = settings.timezone

        if settings.enable_today_report:
            cron_expression = reporting.to_cron_expression(settings.morning_report_time)
            if cron_expression:
                await self.context.cron_manager.add_basic_job(
                    name=self._job_name("today"),
                    cron_expression=cron_expression,
                    handler=self._run_scheduled_report,
                    description="Dida365 scheduled today report",
                    timezone=timezone,
                    payload={"report_type": "today"},
                    enabled=True,
                    persistent=False,
                )
            else:
                logger.warning(
                    "Skip Dida365 today report scheduling due to invalid morning_report_time: %s",
                    settings.morning_report_time,
                )

        if settings.enable_unfinished_report:
            cron_expression = reporting.to_cron_expression(settings.evening_report_time)
            if cron_expression:
                await self.context.cron_manager.add_basic_job(
                    name=self._job_name("unfinished"),
                    cron_expression=cron_expression,
                    handler=self._run_scheduled_report,
                    description="Dida365 scheduled unfinished report",
                    timezone=timezone,
                    payload={"report_type": "unfinished"},
                    enabled=True,
                    persistent=False,
                )
            else:
                logger.warning(
                    "Skip Dida365 unfinished report scheduling due to invalid evening_report_time: %s",
                    settings.evening_report_time,
                )

    async def _run_scheduled_report(self, report_type: str) -> None:
        reporting = self._build_reporting()
        service = reporting.service
        target_umo = await self._get_effective_report_target()
        if not target_umo:
            logger.warning(
                "Dida365 scheduled report skipped because no target is bound.",
            )
            return

        try:
            await reporting.send_scheduled_report(report_type, target_umo)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Dida365 scheduled report failed for %s: %s",
                report_type,
                exc,
                exc_info=True,
            )
            try:
                error_text = (
                    f"Dida365 scheduled {report_type} report failed.\n"
                    f"Reason: {service.explain_error(exc)}"
                )
                await self.context.send_message(
                    target_umo,
                    MessageChain().message(error_text),
                )
            except Exception:  # noqa: BLE001
                logger.error(
                    "Dida365 failed to send scheduled error message.",
                    exc_info=True,
                )

    async def _run_service_text(
        self,
        operation: Callable[[DidaService], Awaitable[str]],
    ) -> str:
        service = self._build_service()
        try:
            return await operation(service)
        except Exception as exc:  # noqa: BLE001
            return service.explain_error(exc)

    async def _run_task_ops_text(
        self,
        operation: Callable[[DidaTaskOpsCoordinator], Awaitable[str]],
    ) -> str:
        service = self._build_service()
        task_ops = self._build_task_ops()
        try:
            return await operation(task_ops)
        except Exception as exc:  # noqa: BLE001
            return service.explain_error(exc)

    async def _build_report_status(self) -> str:
        settings = self._build_settings()
        reporting = self._build_reporting()
        effective_target = await self._get_effective_report_target()
        bound_target = await self._get_bound_report_target()
        timezone = settings.timezone
        jobs = await self._list_report_jobs()
        job_map = {}
        for job in jobs:
            report_type = job.name.rsplit(":", 1)[-1]
            job_map[report_type] = job

        lines = [
            "滴答清单汇报状态",
            f"- 已启用主动汇报: {settings.enable_daily_briefing}",
            f"- 汇报模式: {settings.report_mode}",
            f"- 时区: {timezone}",
            f"- 已绑定汇报目标: {bool(bound_target)}",
            f"- 已配置汇报目标: {bool(settings.report_target)}",
            f"- 当前存在有效汇报目标: {bool(effective_target)}",
            f"- 启用今日任务早报: {settings.enable_today_report}",
            f"- 早报时间: {settings.morning_report_time or '(未设置)'}",
            (
                f"- 早报时间有效: "
                f"{bool(reporting.parse_report_time(settings.morning_report_time))}"
            ),
            f"- 启用未完成任务晚报: {settings.enable_unfinished_report}",
            f"- 晚报时间: {settings.evening_report_time or '(未设置)'}",
            (
                f"- 晚报时间有效: "
                f"{bool(reporting.parse_report_time(settings.evening_report_time))}"
            ),
            f"- LLM 汇报最多包含任务数: {settings.llm_max_tasks}",
            (
                f"- 今日汇报包含逾期任务: "
                f"{settings.include_overdue_in_today_report}"
            ),
            f"- 启用自然语言任务操作: {settings.enable_llm_task_ops}",
            f"- 低风险写操作需要确认: {settings.confirm_low_risk_writes}",
            f"- 高风险写操作需要确认: {settings.confirm_high_risk_writes}",
            (
                f"- 确认等待超时（秒）: "
                f"{settings.confirmation_timeout_seconds}"
            ),
        ]
        if settings.report_mode == "llm":
            lines.append(
                (
                    f"- 汇报 Prompt: "
                    f"{'自定义' if settings.llm_report_prompt.strip() else '默认'}"
                ),
            )
        lines.append(
            (
                f"- 任务操作 Prompt: "
                f"{'自定义' if settings.llm_task_ops_prompt.strip() else '默认'}"
            ),
        )

        if job_map:
            lines.append("- 已注册定时任务:")
            for report_type in ("today", "unfinished"):
                job = job_map.get(report_type)
                if not job:
                    continue
                next_run = (
                    job.next_run_time.isoformat() if job.next_run_time else "(无)"
                )
                lines.append(f"  - {report_type}: next_run={next_run}")
        else:
            lines.append("- 已注册定时任务: (无)")
        return "\n".join(lines)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_ping")
    async def dida_ping(self, event: AstrMessageEvent):
        """Check whether the Dida365 plugin is loaded."""
        yield event.plain_result(self._build_service().build_status_summary())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_probe")
    async def dida_probe(self, event: AstrMessageEvent):
        """Run a minimal read-only Dida365 API probe."""
        yield event.plain_result(
            await self._run_service_text(lambda service: service.probe_read_access())
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_projects")
    async def dida_projects(self, event: AstrMessageEvent):
        """List Dida365 projects with a minimal read-only API call."""
        yield event.plain_result(
            await self._run_service_text(
                lambda service: service.list_projects_summary()
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_project_data")
    async def dida_project_data(
        self,
        event: AstrMessageEvent,
        project_id: str = "",
    ):
        """Load one project's data for future task filtering."""
        service = self._build_service()
        target_project_id = project_id or str(
            self.config.get("default_project", "") or "",
        )
        if not target_project_id:
            yield event.plain_result(
                "No project_id provided. Pass one explicitly or configure default_project first.",
            )
            return
        try:
            yield event.plain_result(
                await service.get_project_data_summary(target_project_id),
            )
        except Exception as exc:
            yield event.plain_result(service.explain_error(exc))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_today")
    async def dida_today(self, event: AstrMessageEvent):
        """List tasks due today."""
        yield event.plain_result(
            await self._run_service_text(
                lambda service: service.list_today_tasks_summary()
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_unfinished")
    async def dida_unfinished(self, event: AstrMessageEvent):
        """List unfinished tasks."""
        yield event.plain_result(
            await self._run_service_text(
                lambda service: service.list_unfinished_tasks_summary()
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_bind_report_target")
    async def dida_bind_report_target(self, event: AstrMessageEvent):
        """Bind the current session as the proactive report target."""
        await self.put_kv_data(self.REPORT_TARGET_KV_KEY, event.unified_msg_origin)
        await self._sync_report_jobs()
        yield event.plain_result("已将当前会话绑定为滴答清单主动汇报目标。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_report_status")
    async def dida_report_status(self, event: AstrMessageEvent):
        """Show current scheduled report status."""
        await self._sync_report_jobs()
        yield event.plain_result(await self._build_report_status())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_do")
    async def dida_do(self, event: AstrMessageEvent, instruction: str = ""):
        """Parse natural-language task instructions with the current session LLM."""
        yield event.plain_result(
            await self._run_task_ops_text(
                lambda task_ops: task_ops.handle_instruction(event, instruction)
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_confirm")
    async def dida_confirm(self, event: AstrMessageEvent):
        """Confirm the pending Dida365 task operation in the current chat."""
        yield event.plain_result(
            await self._run_task_ops_text(
                lambda task_ops: task_ops.confirm_pending(event)
            )
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dida_cancel")
    async def dida_cancel(self, event: AstrMessageEvent):
        """Cancel the pending Dida365 task operation in the current chat."""
        yield event.plain_result(
            await self._run_task_ops_text(
                lambda task_ops: task_ops.cancel_pending(event)
            )
        )
