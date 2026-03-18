# 滴答清单连接器

AstrBot 上的 Dida365（滴答清单）连接插件。
插件提供 Dida365 任务查询、定时主动汇报，以及基于 LLM 的自然语言任务操作能力。

当前版本使用手动 `access_token` 模式。
根据 Dida365 token 接口返回的 `expires_in` 示例，access token 有效期通常约为 180 天（约15551999 秒）。
到期后请手动更新插件配置中的 `access_token`。

## 1. 功能简介

插件当前支持：
- 今日任务查询
- 未完成任务查询
- 项目列表与项目数据摘要
- 定时主动汇报
- 基于 LLM 的自然语言任务操作
- 写操作确认机制

当前支持的自然语言动作：
- `create_task`
- `complete_task`
- `update_task`
- `move_task`
- `delete_task`
- `batch_complete_tasks`（保守版批量完成）

## 2. 安装方法

### 2.1 通过插件市场安装

在 AstrBot 插件市场中搜索 `滴答清单连接器`、`dida365` 或 `astrbot_plugin_dida365`，然后点击安装。

### 2.2 通过仓库地址安装

如果你使用手动安装方式，可以在 AstrBot 插件安装界面中填写这个仓库地址：

```text
https://github.com/zhenyumi/astrbot_plugin_dida365.git
```

## 3. 快速开始

1. 获取 Dida365 `access_token`
2. 在插件配置中填写 `access_token`
3. 按需要填写 `default_project` 和 `timezone`
4. 执行 `/dida_ping` 确认插件已加载
5. 执行 `/dida_probe` 确认 API 可用
6. 执行 `/dida_today` 和 `/dida_unfinished` 确认查询正常

## 4. 配置说明

实际配置文件通常位于：
- `data/config/astrbot_plugin_dida365_config.json`

仓库中提供中文注释示例：
- `data/plugins/astrbot_plugin_dida365/config.example.jsonc`

### 4.1 插件当前保留的配置项

| 配置项 | 是否必填 | 作用 | 说明 |
| --- | --- | --- | --- |
| `access_token` | 是 | Dida365 API 认证凭据 | 当前版本最关键的配置项 |
| `api_base_url` | 是 | Dida365 Open API 基础地址 | 通常使用默认值 |
| `default_project` | 否 | 自然语言操作的默认项目 | 未显式提到项目时使用 |
| `request_timeout_seconds` | 否 | API 请求超时时间 | 单位秒 |
| `timezone` | 否 | 插件业务时区 | 留空时跟随 AstrBot 全局 timezone |
| `enable_daily_briefing` | 否 | 主动汇报总开关 | 需要时打开 |
| `morning_report_time` | 否 | 今日任务早报时间 | 格式 `HH:MM` |
| `evening_report_time` | 否 | 未完成任务晚报时间 | 格式 `HH:MM` |
| `report_target` | 否 | 备用汇报目标会话 | 更推荐使用 `/dida_bind_report_target` |
| `enable_today_report` | 否 | 是否启用今日早报 | 配合总开关使用 |
| `enable_unfinished_report` | 否 | 是否启用晚报 | 配合总开关使用 |
| `report_mode` | 否 | 主动汇报模式 | `direct` 或 `llm` |
| `llm_report_prompt` | 否 | 自定义汇报 Prompt | 可选 |
| `llm_max_tasks` | 否 | 送给 LLM 的最大任务数 | 避免上下文过长 |
| `include_overdue_in_today_report` | 否 | 今日早报是否包含逾期任务 | 按需开启 |
| `enable_llm_task_ops` | 否 | 是否启用自然语言任务操作 | 默认开启 |
| `llm_task_ops_prompt` | 否 | 自定义意图解析 Prompt | 可选 |
| `confirm_low_risk_writes` | 否 | 低风险写操作是否需要确认 | 影响 create/complete/update |
| `confirm_high_risk_writes` | 否 | 高风险写操作是否需要确认 | 影响 move/delete/batch |
| `confirmation_timeout_seconds` | 否 | 确认等待超时时间 | 单位秒 |

### 4.2 重点配置项解释

- `access_token`
  - 当前版本必填。
  - Dida365 所有读写 API 都需要它。
  - 有效期通常约 180 天，到期后需手动更新。
- `timezone`
  - 决定 `/dida_today`、逾期判断、主动汇报时间、自然语言里的“明天”、“今晚”等概念。
  - 推荐填写 `Asia/Shanghai` 这类 IANA 时区名称。
- `default_project`
  - 如果你的自然语言指令没有明确指出项目，插件会优先使用这里配置的项目。
- `report_mode`
  - `direct`：插件直接生成稳定文本。
  - `llm`：插件先整理结构化任务内容，再交给 LLM 生成汇报文案。
- `confirm_low_risk_writes`
  - 控制 `create_task`、`complete_task`、`update_task` 是否也需要确认。
- `confirm_high_risk_writes`
  - 控制 `move_task`、`delete_task`、`batch_complete_tasks` 是否需要确认。
  - 默认建议保持 `true`。

## 5. 命令说明

### 5.1 查询与诊断
- `/dida_ping`
  - 作用：查看插件是否已加载，以及当前关键配置摘要。
  - 适合在初始配置后首先执行。
- `/dida_probe`
  - 作用：用最小只读 API 检查 `access_token` 是否可用。
  - 如果这个命令失败，通常优先检查 token 本身。
- `/dida_projects`
  - 作用：列出项目摘要。
  - 适合用来确认项目名、项目 ID。
- `/dida_project_data <project_id>`
  - 作用：查看单个项目的数据摘要。
  - 适合 API 联调时使用。
- `/dida_today`
  - 作用：查询今天到期且未完成的任务。
  - “今天”的判断使用 `timezone` 配置。
- `/dida_unfinished`
  - 作用：查询未完成任务。
  - 会优先展示更紧急、更值得关注的任务。

### 5.2 主动汇报
- `/dida_bind_report_target`
  - 作用：将当前会话绑定为主动汇报目标。
  - 建议在你希望接收汇报的聊天窗口里执行一次。
- `/dida_report_status`
  - 作用：查看当前主动汇报开关、时间、目标会话和 `next_run`。
  - 配置完时间后建议执行一次确认。

### 5.3 自然语言任务操作
- `/dida_do <自然语言指令>`
  - 作用：让当前会话 LLM 先解析意图，再由插件做任务匹配、参数校验、确认与执行。
  - 示例：
    - `/dida_do 明天创建一个洗澡任务`
    - `/dida_do 把买牛奶标记完成`
    - `/dida_do 把洗澡任务改到明天晚上十一点`
    - `/dida_do 删除洗澡任务`
- `/dida_confirm`
  - 作用：确认待执行操作。
- `/dida_cancel`
  - 作用：取消当前待执行操作。

## 6. Dida365 手动获取 Access Token 指南

### 6.1 创建应用

在 Dida365 开发者平台创建 app（https://developer.dida365.com/manage），获得：
- Client ID
- Client Secret

同时配置好回调地址，例如：

```text
http://localhost:8000/callback
```

### 6.2 打开授权链接

在浏览器访问：

```text
https://dida365.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost:8000/callback&scope=tasks:read%20tasks:write&state=123
```

完成登录并授权。

### 6.3 从回调地址取出 code

授权成功后，浏览器会跳转到类似地址：

```text
http://localhost:8000/callback?code=ABC123&state=123
```

取出其中的 `code`。

### 6.4 生成 Basic 认证字符串

把下面这串内容：

```text
ClientID:ClientSecret
```

做 Base64 编码。

在 PowerShell 中可用：

```powershell
$plain = "你的ClientID:你的ClientSecret"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($plain)
[Convert]::ToBase64String($bytes)
```

### 6.5 用 code 换取 access token

在 PowerShell 中执行：

```powershell
curl.exe -X POST "https://dida365.com/oauth/token" -H "Authorization: Basic 你的Base64结果" -H "Content-Type: application/x-www-form-urlencoded" --data-urlencode "grant_type=authorization_code" --data-urlencode "code=你的code" --data-urlencode "redirect_uri=http://localhost:8000/callback"
```

### 6.6 获取结果

成功后会返回类似：

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_in": 15551999,
  "scope": "tasks:read tasks:write"
}
```

### 6.7 注意事项

- `redirect_uri` 必须和开发者后台配置的完全一致
- `code` 通常只能用一次，过期后需要重新授权
- 不要泄露 Client Secret 和 access_token

## 7. 主动汇报使用方式

1. 在目标会话执行 `/dida_bind_report_target`
2. 将 `enable_daily_briefing` 设为 `true`
3. 根据需要开启：
   - `enable_today_report`
   - `enable_unfinished_report`
4. 设置 `morning_report_time` 和 `evening_report_time`
5. 执行 `/dida_report_status` 检查当前状态

`report_mode` 说明：
- `direct`：插件直接输出稳定文本，适合调试
- `llm`：插件先整理结构化任务数据，再交给 LLM 生成更自然的汇报

## 8. 自然语言任务操作说明

所有自然语言任务操作都会先经过 LLM 解析。

插件的处理链路：
1. LLM 解析意图
2. 插件做任务匹配、项目匹配、参数校验
3. 插件判断是否需要确认
4. 最后再执行 API 调用

风险分级：
- 低风险：`create_task`、`complete_task`、`update_task`
- 高风险：`move_task`、`delete_task`、`batch_complete_tasks`

默认确认策略：
- `confirm_low_risk_writes = false`
- `confirm_high_risk_writes = true`

## 9. token 使用与更新说明

- 当前版本不自动刷新 `access_token`
- token 通常有效约 180 天
- token 过期后请直接手动更新插件配置
- 如果 Dida365 返回 `401/403`，请优先检查 `access_token` 是否已失效

## 10. 常见问题

### 10.1 `/dida_probe` 提示 access token 未配置
说明你还没有在插件配置中填写 `access_token`。

### 10.2 提示 authentication failed
通常表示 `access_token` 已过期、失效或填写错误。
请手动更新 `access_token`。

### 10.3 `/dida_today` 日期不对
请优先检查 `timezone` 配置。

### 10.4 任务匹配失败或出现多个候选
请提供更完整的任务标题，必要时加上项目名。

### 10.5 主动汇报没有发出
请检查：
- 是否已执行 `/dida_bind_report_target`
- `enable_daily_briefing` 是否为 `true`
- 时间格式是否为 `HH:MM`
- `/dida_report_status` 中是否能看到 `next_run`
- `access_token` 是否仍然有效

## 11. 示例配置

请参考：
- `data/plugins/astrbot_plugin_dida365/config.example.jsonc`

