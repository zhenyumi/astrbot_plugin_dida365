from __future__ import annotations

import json
import re

from astrbot.api import logger
from astrbot.core.astr_main_agent import _get_session_conv
from astrbot.core.astr_main_agent_resources import (
    CHATUI_SPECIAL_DEFAULT_PERSONA_PROMPT,
)
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.provider.entities import ProviderRequest

from .exceptions import DidaConfigurationError, DidaError
from .service import DidaService
from .time_utils import now_in_timezone
from .types import DidaPluginSettings, DidaStructuredReport

_DEFAULT_LLM_REPORT_PROMPT = """你是一个任务汇报助手。下面会提供已经筛选和整理好的任务汇报数据。
你的职责：
1. 基于提供的数据生成简洁、清晰、忠于事实的汇报。
2. 不要编造不存在的任务、项目、时间或优先级。
3. 不要修改任务事实。
4. 可以根据当前人格风格调整语气，但不要影响事实准确性。
5. 先总结整体情况，再列出最重要的任务。
6. 如果没有任务，直接明确说明。
7. 输出适合作为聊天消息直接发送。

以下是结构化任务汇报输入：
{structured_report_input}
"""

_TIME_PATTERN = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")


class DidaReportingCoordinator:
    def __init__(
        self, context, settings: DidaPluginSettings, service: DidaService
    ) -> None:
        self.context = context
        self.settings = settings
        self.service = service

    @staticmethod
    def parse_report_time(value: str) -> tuple[int, int] | None:
        text = str(value or "").strip()
        match = _TIME_PATTERN.fullmatch(text)
        if not match:
            return None
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if hour not in range(24) or minute not in range(60):
            return None
        return hour, minute

    @classmethod
    def to_cron_expression(cls, value: str) -> str | None:
        parsed = cls.parse_report_time(value)
        if not parsed:
            return None
        hour, minute = parsed
        return f"{minute} {hour} * * *"

    async def send_scheduled_report(self, report_type: str, target_umo: str) -> str:
        if not target_umo:
            raise DidaConfigurationError(
                "未配置主动汇报目标会话，请先执行 /dida_bind_report_target。",
            )

        message_text = await self.generate_report_message(
            report_type=report_type,
            target_umo=target_umo,
        )
        ok = await self.context.send_message(
            target_umo,
            MessageChain().message(message_text),
        )
        if not ok:
            raise DidaError(f"向目标会话发送滴答清单主动汇报失败：{target_umo}")
        return message_text

    async def generate_report_message(
        self,
        *,
        report_type: str,
        target_umo: str,
    ) -> str:
        report = await self._build_report(report_type)
        direct_text = self.service.render_direct_report(report)
        if self.settings.report_mode != "llm":
            return direct_text

        try:
            llm_text = await self._generate_llm_report(
                report=report,
                target_umo=target_umo,
            )
            if llm_text:
                return llm_text
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Dida365 LLM report generation failed, fallback to direct mode: %s",
                exc,
                exc_info=True,
            )
            return f"LLM 汇报生成失败，已回退为 direct 模式。\n\n{direct_text}"

        return direct_text

    async def _build_report(self, report_type: str) -> DidaStructuredReport:
        now = now_in_timezone(self.settings.timezone)
        if report_type == "today":
            return await self.service.build_today_report(
                now=now,
                include_overdue=self.settings.include_overdue_in_today_report,
                max_tasks=self.settings.llm_max_tasks,
            )
        if report_type == "unfinished":
            return await self.service.build_unfinished_report(
                now=now,
                max_tasks=self.settings.llm_max_tasks,
            )
        raise DidaConfigurationError(f"不支持的滴答清单汇报类型：{report_type}")

    async def _generate_llm_report(
        self,
        *,
        report: DidaStructuredReport,
        target_umo: str,
    ) -> str:
        provider = self.context.get_using_provider(target_umo)
        if not provider:
            raise DidaConfigurationError("当前汇报目标会话没有可用的聊天模型。")

        session = MessageSession.from_str(target_umo)
        conversation = await self._get_conversation_for_target(target_umo)
        provider_settings = self.context.get_config(umo=target_umo).get(
            "provider_settings",
            {},
        )
        system_prompt, persona_contexts = await self._build_persona_context(
            target_umo=target_umo,
            conversation_persona_id=conversation.persona_id,
            session=session,
            provider_settings=provider_settings,
        )

        structured_report_input = self.service.build_structured_report_input(report)
        prompt = self._compose_llm_prompt(structured_report_input)
        req = ProviderRequest(
            prompt=prompt,
            session_id=target_umo,
            contexts=persona_contexts,
            system_prompt=system_prompt,
            conversation=conversation,
        )
        llm_resp = await provider.text_chat(
            prompt=req.prompt,
            session_id=req.session_id,
            contexts=req.contexts,
            system_prompt=req.system_prompt,
        )
        completion = (llm_resp.completion_text or "").strip()
        if not completion:
            raise DidaError("LLM 返回了空的滴答清单汇报内容。")
        return completion

    async def _get_conversation_for_target(self, target_umo: str):
        session = MessageSession.from_str(target_umo)

        class _SyntheticEvent:
            def __init__(self, umo: str, platform_id: str) -> None:
                self.unified_msg_origin = umo
                self._platform_id = platform_id

            def get_platform_id(self) -> str:
                return self._platform_id

        return await _get_session_conv(
            _SyntheticEvent(target_umo, session.platform_id),
            self.context,
        )

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

    def _compose_llm_prompt(self, structured_report_input: str) -> str:
        template = self.settings.llm_report_prompt.strip() or _DEFAULT_LLM_REPORT_PROMPT
        if "{structured_report_input}" in template:
            return template.replace(
                "{structured_report_input}", structured_report_input
            )
        return f"{template}\n\n{structured_report_input}"
