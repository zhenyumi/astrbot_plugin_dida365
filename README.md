# 滴答清单连接器

滴答清单连接器是一个 AstrBot 插件，用于连接 Dida365（滴答清单）Open API。

当前版本支持：
- 查询今日任务
- 查询未完成任务
- 定时主动汇报
- 基于 LLM 的自然语言任务操作

当前版本不支持：
- 自动刷新 Access Token
- 自然语言设置定时汇报时间
- 批量任务操作

插件当前使用手动 `access_token` 模式。根据 Dida365 token 接口返回的 `expires_in` 示例，access token 有效期通常约为 180 天。到期后请手动更新插件配置中的 `access_token`。

## 安装方式

### 方式一：通过 AstrBot 插件市场安装

在 AstrBot 插件市场中搜索以下关键词：
- `滴答清单连接器`
- `dida365`
- `astrbot_plugin_dida365`

然后点击安装即可。

### 方式二：通过仓库地址安装

在 AstrBot 插件安装界面中填入仓库地址：

```text
https://github.com/zhenyumi/astrbot_plugin_dida365.git
```

## 快速开始

1. 先获取 Dida365 `access_token`
2. 在插件配置中填写 `access_token`
3. 按需要设置 `default_project` 和 `timezone`
4. 执行 `/dida_ping` 检查插件是否已加载
5. 执行 `/dida_probe` 检查当前 token 是否可用
6. 执行 `/dida_today` 或 `/dida_unfinished` 验证读取能力

## 配置文件位置

AstrBot 实际运行时配置通常保存在：

```text
data/config/astrbot_plugin_dida365_config.json
```

本仓库提供了一个中文注释版示例配置：

```text
data/plugins/astrbot_plugin_dida365/config.example.jsonc
```

## 配置项说明

### 认证与基础配置

| 配置项 | 是否必填 | 作用 | 说明 |
| --- | --- | --- | --- |
| `access_token` | 是 | Dida365 API 认证凭据 | 当前版本必须手动维护，有效期通常约 180 天 |
| `api_base_url` | 否 | Dida365 Open API 基础地址 | 一般保持默认值即可 |
| `default_project` | 否 | 默认项目名称或项目 ID | 自然语言任务操作未明确提到项目时优先使用 |
| `request_timeout_seconds` | 否 | API 请求超时 | 单位为秒 |
| `timezone` | 否 | 插件业务时区 | 留空时默认跟随 AstrBot 全局 `timezone` |

### 主动汇报配置

| 配置项 | 是否必填 | 作用 | 说明 |
| --- | --- | --- | --- |
| `enable_daily_briefing` | 否 | 主动汇报总开关 | 早报和晚报都受它控制 |
| `morning_report_time` | 否 | 今日任务汇报时间 | 格式 `HH:MM` |
| `evening_report_time` | 否 | 未完成任务汇报时间 | 格式 `HH:MM` |
| `report_target` | 否 | 备用汇报目标会话 | 更推荐用 `/dida_bind_report_target` 绑定 |
| `enable_today_report` | 否 | 启用今日任务早报 | 配合总开关使用 |
| `enable_unfinished_report` | 否 | 启用未完成任务晚报 | 配合总开关使用 |
| `report_mode` | 否 | 汇报模式 | `direct` 或 `llm` |
| `llm_report_prompt` | 否 | 自定义汇报 Prompt | 可使用 `{structured_report_input}` 占位符 |
| `llm_max_tasks` | 否 | 送给 LLM 的最大任务数 | 用于控制输入规模 |
| `include_overdue_in_today_report` | 否 | 今日汇报是否包含逾期任务 | 关闭时只汇报今日到期任务 |

### 自然语言任务操作配置

| 配置项 | 是否必填 | 作用 | 说明 |
| --- | --- | --- | --- |
| `enable_llm_task_ops` | 否 | 启用自然语言任务操作 | 开启后 `/dida_do` 才能使用 |
| `llm_task_ops_prompt` | 否 | 自定义意图解析 Prompt | 插件管理界面中默认已经预填内置 Prompt 全文，可直接查看和修改 |
| `confirm_low_risk_writes` | 否 | 低风险写操作是否需要确认 | 影响 `create_task`、`complete_task`、`update_task` |
| `confirm_high_risk_writes` | 否 | 高风险写操作是否需要确认 | 影响 `move_task`、`delete_task` |
| `confirmation_timeout_seconds` | 否 | 等待确认超时 | 单位为秒 |

## 命令列表

### 查询与诊断

#### `/dida_ping`

作用：
- 检查插件是否已加载
- 返回最小非敏感状态摘要

适合：
- 插件刚安装完成后先执行一次
- 检查关键开关是否已经生效

#### `/dida_probe`

作用：
- 用最小只读 API 检查 `access_token` 是否可用

适合：
- 刚填好 token 后测试
- token 到期后重新验证

#### `/dida_projects`

作用：
- 列出当前可访问的项目摘要

适合：
- 确认项目名称
- 确认项目 ID

#### `/dida_project_data <project_id>`

作用：
- 读取单个项目的数据摘要

适合：
- API 联调
- 验证某个项目中的任务读取是否正常

#### `/dida_today`

作用：
- 查询今日到期且未完成的任务

说明：
- “今日”的判定使用插件配置中的 `timezone`

#### `/dida_unfinished`

作用：
- 查询未完成任务

说明：
- 会根据逾期情况、截止时间和优先级做展示整理

### 主动汇报

#### `/dida_bind_report_target`

作用：
- 把当前会话绑定为主动汇报目标

建议：
- 在你希望接收汇报的聊天窗口中执行一次

#### `/dida_report_status`

作用：
- 查看当前主动汇报状态
- 检查时间配置和下次触发时间

### 自然语言任务操作

#### `/dida_do <自然语言指令>`

作用：
- 让当前会话的 LLM 先解析意图
- 再由插件执行任务匹配、参数校验、确认判断和最终 API 调用

当前支持的动作：
- `create_task`
- `complete_task`
- `update_task`
- `move_task`
- `delete_task`

示例：

```text
/dida_do 明天创建一个洗澡任务
/dida_do 把买牛奶标记完成
/dida_do 把洗澡任务改到明天晚上十一点
/dida_do 把洗澡任务移到生活项目
/dida_do 删除洗澡任务
```

#### `/dida_confirm`

作用：
- 确认执行当前待确认操作

#### `/dida_cancel`

作用：
- 取消当前待确认操作

## 主动汇报使用说明

1. 在目标会话执行 `/dida_bind_report_target`
2. 将 `enable_daily_briefing` 设为 `true`
3. 视需要开启：
   - `enable_today_report`
   - `enable_unfinished_report`
4. 设置 `morning_report_time` 和 `evening_report_time`
5. 执行 `/dida_report_status` 检查状态

`report_mode` 说明：
- `direct`：插件直接输出稳定文本，适合调试
- `llm`：插件先整理结构化任务数据，再交给当前会话模型生成更自然的汇报

## 自然语言任务操作说明

所有自然语言任务操作都会先经过 LLM 解析，插件不会绕过 LLM 直接按规则执行。

处理链路如下：
1. LLM 解析任务意图
2. 插件做任务匹配、项目匹配和参数校验
3. 插件判断是否需要确认
4. 插件再执行最终 API 调用

### 风险分级

- 低风险：`create_task`、`complete_task`、`update_task`
- 高风险：`move_task`、`delete_task`

### 默认确认策略

- `confirm_low_risk_writes = false`
- `confirm_high_risk_writes = true`

### 关于默认 LLM Prompt

插件管理界面的 `llm_task_ops_prompt` 配置项中，默认已经预填内置 Prompt 全文。你可以：
- 直接查看默认 Prompt
- 在原 Prompt 基础上微调
- 清空后恢复使用插件代码中的同款默认 Prompt

## Dida365 手动获取 Access Token 指南

### 1. 创建应用

在 Dida365 开发者平台创建 app，获得：
- Client ID
- Client Secret

同时配置好回调地址，例如：

```text
http://localhost:8000/callback
```

### 2. 打开授权链接

在浏览器访问：

```text
https://dida365.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost:8000/callback&scope=tasks:read%20tasks:write&state=123
```

完成登录并授权。

### 3. 从回调地址中取出 code

授权成功后，浏览器会跳转到类似地址：

```text
http://localhost:8000/callback?code=ABC123&state=123
```

取出其中的 `code`。

### 4. 生成 Basic 认证字符串

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

### 5. 用 code 换取 access token

在 PowerShell 中执行：

```powershell
curl.exe -X POST "https://dida365.com/oauth/token" -H "Authorization: Basic 你的Base64结果" -H "Content-Type: application/x-www-form-urlencoded" --data-urlencode "grant_type=authorization_code" --data-urlencode "code=你的code" --data-urlencode "redirect_uri=http://localhost:8000/callback"
```

### 6. 获取结果

成功后会返回类似：

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_in": 15551999,
  "scope": "tasks:read tasks:write"
}
```

之后调用 API 时，在请求头里加：

```text
Authorization: Bearer 你的access_token
```

### 注意事项

- `redirect_uri` 必须和后台配置的一致
- `code` 通常只能用一次，过期后需要重新授权
- 不要泄露 `Client Secret` 和 `access_token`
- 在 PowerShell 里建议用 `curl.exe`，不要直接用 `curl`

## Token 使用与更新说明

- 当前版本不自动刷新 `access_token`
- `access_token` 有效期通常约 180 天
- token 过期后，请手动更新插件配置中的 `access_token`
- 如果 Dida365 返回 `401` 或 `403`，请优先检查 token 是否已失效

## 常见问题

### `/dida_probe` 提示 access token 未配置

说明你还没有在插件配置中填写 `access_token`。

### 提示认证失败

通常表示 `access_token` 已过期、已失效或填写错误，请手动更新后再试。

### `/dida_today` 日期不对

优先检查 `timezone` 配置。若留空，则会跟随 AstrBot 全局 `timezone`。

### 任务匹配失败或匹配到多个任务

请提供更明确的任务标题，必要时补充项目名称。

### 主动汇报没有发出

请检查：
- 是否已经执行 `/dida_bind_report_target`
- `enable_daily_briefing` 是否为 `true`
- 汇报时间格式是否为 `HH:MM`
- `/dida_report_status` 是否能看到 `next_run`
- `access_token` 是否仍然有效
