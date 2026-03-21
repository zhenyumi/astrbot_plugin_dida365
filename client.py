from __future__ import annotations

import json
import re
from typing import Any

import aiohttp

from astrbot.api import logger

from .exceptions import (
    DidaApiError,
    DidaAuthenticationError,
    DidaConfigurationError,
    DidaNetworkError,
    DidaNotFoundError,
)
from .types import DidaPluginSettings, DidaProject, DidaProjectData, DidaTask

_SENSITIVE_PAYLOAD_KEYS = {"title", "content", "desc", "description", "note"}


def _sanitize_log_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).casefold() in _SENSITIVE_PAYLOAD_KEYS:
                sanitized[key] = "***"
            else:
                sanitized[key] = _sanitize_log_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_log_payload(item) for item in value]
    return value


_TOKEN_FIELD_PATTERN = re.compile(
    r"""(?P<key>access_token|Authorization|invalid access token)(?P<sep>["'=: ]+)(?P<value>[^",\s}]+|"[^"]*"|'[^']*')""",
    re.IGNORECASE,
)


def _redact_sensitive_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        key = match.group("key")
        sep = match.group("sep")
        raw_value = match.group("value")
        if raw_value.startswith('"') and raw_value.endswith('"'):
            redacted_value = '"***"'
        elif raw_value.startswith("'") and raw_value.endswith("'"):
            redacted_value = "'***'"
        else:
            redacted_value = "***"
        return f"{key}{sep}{redacted_value}"

    return _TOKEN_FIELD_PATTERN.sub(_replace, text)


class DidaClient:
    """Minimal Dida365 Open API client focused on plugin reads and task writes."""

    def __init__(
        self,
        settings: DidaPluginSettings,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.settings = settings
        self._session = session

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise DidaConfigurationError(
                "Dida365 HTTP client is not initialized. Please reload the plugin and try again.",
            )
        return self._session

    def _build_headers(self, settings: DidaPluginSettings) -> dict[str, str]:
        if not settings.access_token:
            raise DidaConfigurationError(
                "Dida365 access_token is not configured. Please fill it in the plugin config first.",
            )
        return {
            "Authorization": f"Bearer {settings.access_token}",
            "Content-Type": "application/json",
        }

    def _build_url(self, settings: DidaPluginSettings, path: str) -> str:
        base_url = settings.api_base_url.strip().rstrip("/")
        if not base_url:
            raise DidaConfigurationError(
                "Dida365 api_base_url is not configured. Please fill it in the plugin config first.",
            )
        return f"{base_url}/{path.lstrip('/')}"

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request_json_once(
            method,
            path,
            settings=self.settings,
            params=params,
            json_body=json_body,
        )

    async def _request_json_once(
        self,
        method: str,
        path: str,
        *,
        settings: DidaPluginSettings,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
        url = self._build_url(settings, path)
        headers = self._build_headers(settings)
        session = self._get_session()
        if json_body is not None and method.upper() in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            logger.debug(
                "Dida365 API request %s %s payload=%s",
                method.upper(),
                path,
                _redact_sensitive_text(
                    json.dumps(
                        _sanitize_log_payload(json_body),
                        ensure_ascii=False,
                    )
                ),
            )
        try:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            ) as response:
                body_text = await response.text()
                if response.status in (401, 403):
                    logger.error(
                        "Dida365 API response %s %s status=%s body=%s",
                        method.upper(),
                        path,
                        response.status,
                        _redact_sensitive_text(body_text[:2000]),
                    )
                    raise DidaAuthenticationError(
                        "Dida365 authentication failed. The access token may have expired or become invalid. Please update access_token manually in the plugin config.",
                        status=response.status,
                        payload=_redact_sensitive_text(body_text[:500]),
                    )
                if response.status == 404:
                    logger.error(
                        "Dida365 API response %s %s status=%s body=%s",
                        method.upper(),
                        path,
                        response.status,
                        _redact_sensitive_text(body_text[:2000]),
                    )
                    raise DidaNotFoundError(
                        "The requested Dida365 resource was not found.",
                        status=response.status,
                        payload=_redact_sensitive_text(body_text[:500]),
                    )
                if response.status >= 400:
                    logger.error(
                        "Dida365 API response %s %s status=%s body=%s",
                        method.upper(),
                        path,
                        response.status,
                        _redact_sensitive_text(body_text[:2000]),
                    )
                    raise DidaApiError(
                        f"Dida365 API request failed with status {response.status}.",
                        status=response.status,
                        payload=_redact_sensitive_text(body_text[:500]),
                    )
                if not body_text.strip():
                    return {}
                try:
                    return json.loads(body_text)
                except json.JSONDecodeError as exc:
                    raise DidaApiError(
                        "Dida365 API returned a non-JSON response.",
                        status=response.status,
                        payload=_redact_sensitive_text(body_text[:500]),
                    ) from exc
        except aiohttp.ClientError as exc:
            raise DidaNetworkError(
                f"Unable to reach the Dida365 API: {exc!s}",
            ) from exc
        except TimeoutError as exc:
            raise DidaNetworkError(
                "The Dida365 API request timed out. Please try again later.",
            ) from exc

    async def list_projects(self) -> list[DidaProject]:
        data = await self._request_json("GET", "/project")
        if not isinstance(data, list):
            raise DidaApiError("Unexpected project list response from Dida365 API.")
        return [DidaProject.from_api(item) for item in data if isinstance(item, dict)]

    async def get_project(self, project_id: str) -> DidaProject:
        data = await self._request_json("GET", f"/project/{project_id}")
        if not isinstance(data, dict):
            raise DidaApiError("Unexpected project detail response from Dida365 API.")
        return DidaProject.from_api(data)

    async def get_project_data(self, project_id: str) -> DidaProjectData:
        data = await self._request_json("GET", f"/project/{project_id}/data")
        if not isinstance(data, dict):
            raise DidaApiError("Unexpected project data response from Dida365 API.")
        return DidaProjectData.from_api(data)

    async def get_task(self, project_id: str, task_id: str) -> DidaTask:
        data = await self._request_json("GET", f"/project/{project_id}/task/{task_id}")
        if not isinstance(data, dict):
            raise DidaApiError("Unexpected task detail response from Dida365 API.")
        return DidaTask.from_api(data)

    async def create_task(self, payload: dict[str, Any]) -> DidaTask:
        data = await self._request_json("POST", "/task", json_body=payload)
        if not isinstance(data, dict):
            raise DidaApiError("Unexpected task creation response from Dida365 API.")
        return DidaTask.from_api(data)

    async def update_task(self, task_id: str, payload: dict[str, Any]) -> DidaTask:
        data = await self._request_json("POST", f"/task/{task_id}", json_body=payload)
        if not isinstance(data, dict):
            raise DidaApiError("Unexpected task update response from Dida365 API.")
        return DidaTask.from_api(data)

    async def complete_task(self, project_id: str, task_id: str) -> None:
        data = await self._request_json(
            "POST",
            f"/project/{project_id}/task/{task_id}/complete",
        )
        if data and not isinstance(data, dict):
            raise DidaApiError("Unexpected task completion response from Dida365 API.")

    async def delete_task(self, project_id: str, task_id: str) -> None:
        logger.debug(
            "Dida365 API request %s %s",
            "DELETE",
            f"/project/{project_id}/task/{task_id}",
        )
        data = await self._request_json(
            "DELETE",
            f"/project/{project_id}/task/{task_id}",
        )
        if data and not isinstance(data, dict):
            raise DidaApiError("Unexpected task delete response from Dida365 API.")
