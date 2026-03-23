<div align="center">

# 💂 QQ 群哨兵

<i>👀 BIG BROTHER IS WATCHING YOU!</i>

![License](https://img.shields.io/badge/license-AGPL--3.0-green?style=flat-square)
![Python](https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python&logoColor=white)
![AstrBot](https://img.shields.io/badge/framework-AstrBot-ff6b6b?style=flat-square)

</div>

## 📖 简介

一款为 [**AstrBot**](https://github.com/AstrBotDevs/AstrBot) 设计的群聊监控插件。它支持按关键词、正则表达式、消息类型进行识别及精细的监控时段控制，命中后自动执行撤回、禁言、累计踢出，并提供管理员可用的指令规则管理。

---

## 🚀 功能特性

- 🔍 全量内容检测：支持文本与 JSON 卡片/分享内容检测
- 🎭 多模态规则：支持文本/图片/语音/视频/文件/表情/转发/卡片等消息类型
- 🕒 时间段监控：支持设置规则生效时间段，支持跨天配置
- 📝 关键词规则：配置页规则支持正则；指令规则仅支持普通关键词包含匹配
- 📈 累计违规踢出：支持按规则命中次数踢出
- 🔔 命中通知：支持配置规则通知管理员、指令规则通知创建者
- 🧩 变量模板：支持在回复文本中使用 `{id}`、`{name}`、`{date}`、`{time}` 变量
- 🛡️ 精细权限控制：支持群主豁免、管理员忽略配置以及全局/规则级/指令级多层白名单
- 🧰 指令管理：支持群内添加、删除、查看指令规则

---

## 🎮 指令模块

> 使用权限：仅管理员或 `指令白名单` 用户可用

### ➕ 添加监控

```text
/监控 <关键词> [@某人 ...]
```

示例：

```text
/监控 测试管理 @A @B
```

说明：

- 不 @ 用户：表示全群监控
- 可同时 @ 多人：表示仅监控这些用户
- 关键词不允许纯数字（避免与规则 ID 语义冲突）

---

### ➖ 取消监控

**方式 1：按规则 ID 删除**

```text
/取消监控 <rule_id>
```

**方式 2：按关键词删除（可选 @ 过滤）**

```text
/取消监控 <关键词> [@某人 ...]
```

**方式 3：仅按 @ 用户处理**

```text
/取消监控 @某人
```

处理规则：

- `/取消监控 @某人`：
  - 只处理“指定监控用户规则”
  - 从监控对象中移除该用户
  - 若移除后该规则无监控对象，则删除该规则
  - 全群规则不受影响
- `/取消监控 关键词 @某人`：
  - 只处理匹配关键词且命中该用户的“指定监控用户规则”
  - 执行“移除该用户/空则删除”
  - 全群规则不受影响
- `/取消监控 关键词`（不带 @）：
  - 直接删除当前群中关键词匹配的指令规则

---

### 📋 查看监控

```text
/监控列表
```

返回当前群指令规则列表，包含：

- 规则 ID
- 关键词
- 目标用户（或全体成员）
- 创建者

---

## ⚙️ 配置说明

### 1. 全局配置

| 配置项 | 类型 | 描述 |
| :--- | :--- | :--- |
| `group_blacklist` | `list` | 群聊黑名单，名单中的群不检测 |
| `user_whitelist` | `list` | 全局用户白名单，名单用户不检测 |

### 2. 检测规则配置

支持两种模板：`keyword_rule` 与 `type_rule`。

| 配置项 | 类型 | 说明 |
| :--- | :--- | :--- |
| `keywords` | `list` | 关键词规则使用，支持正则 |
| `msg_types` | `list` | 消息类型规则使用 |
| `time_range` | `string` | 生效时段单字段，如 `2026-10-01~2026-10-07 Mon-Fri 09:00-18:00` |
| `groups` | `list` | 生效群号，留空表示全部群 |
| `mute_duration` | `string` | 禁言秒数或区间，`0` 不禁言，`-1` 不撤回不禁言 |
| `reply_message` | `list` | 命中后随机回复 |
| `ignore_admin` | `bool` | 是否忽略管理员 |
| `notify_group_admin` | `bool` | 是否通知群组管理员 |
| `notify_bot_admin` | `bool` | 是否通知 Bot 管理员 |
| `rule_user_whitelist` | `list` | 规则级用户白名单 |
| `rule_user_monitor_list` | `list` | 规则级监控名单，留空表示全体 |
| `kick_threshold` | `int` | 累计命中踢出阈值 |
| `kick_message` | `list` | 踢出后随机提示 |

### 3. 指令模块配置

通过指令添加的规则统一使用该模块配置。

| 配置项 | 类型 | 说明 |
| :--- | :--- | :--- |
| `command_user_whitelist` | `list` | 指令白名单；该列表用户不会触发指令规则检测 |
| `mute_duration` | `string` | 指令规则禁言时长 |
| `reply_message` | `list` | 指令规则命中后随机回复（支持变量模板） |
| `ignore_admin` | `bool` | 指令规则是否忽略管理员 |
| `kick_threshold` | `int` | 指令规则累计命中踢出阈值 |
| `kick_message` | `list` | 指令规则踢出后随机提示（支持变量模板） |
| `notify_creator` | `bool` | 指令规则命中是否通知规则创建者 |

### 4. 变量模板

可在 `reply_message` 与 `kick_message` 中使用以下变量：

- `{id}`: 触发用户 ID
- `{name}`: 触发用户名
- `{date}`: 当前日期（`YYYY-MM-DD`）
- `{time}`: 当前时间（`HH:MM:SS`）

### 5. 生效时段写法

- 支持把“日期 + 星期 + 时间段”写在一个字段里，空格分隔，顺序可自由组合。
- 例子：
  - `2026-10-01~2026-10-07 Mon-Fri 09:00-18:00`
  - `10-01~10-07 Mon,Fri 22:00-02:00`
  - `01~07 09:00-18:00`
  - `Mon-Fri 09:00-18:00`
  - `09:00-18:00`
- 日期支持：
  - `YYYY-MM-DD` / `YYYY-MM-DD~YYYY-MM-DD`（绝对日期）
  - `MM-DD` / `MM-DD~MM-DD`（每年）
  - `DD` / `DD~DD`（每月）
- 星期仅支持三字母：`Mon` `Tue` `Wed` `Thu` `Fri` `Sat` `Sun`，可用 `Mon-Fri`、`Mon,Fri`。
- 时间支持跨天：如 `22:00-02:00`。

---

## ❤️ 支持

- [AstrBot 帮助文档](https://astrbot.app)
- 如果您在使用中遇到问题，欢迎在本仓库提交 [Issue](https://github.com/Foolllll-J/astrbot_plugin_sentinel/issues)。

---

<div align="center">

**如果本插件对你有帮助，欢迎点个 ⭐ Star 支持一下！**

</div>
