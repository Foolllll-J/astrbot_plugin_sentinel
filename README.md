<div align="center">

# 💂 QQ 群哨兵

<i>👀 BIG BROTHER IS WATCHING YOU!</i>


![License](https://img.shields.io/badge/license-AGPL--3.0-green?style=flat-square)
![Python](https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python&logoColor=white)
![AstrBot](https://img.shields.io/badge/framework-AstrBot-ff6b6b?style=flat-square)

</div>

## 📖 简介

一款为 [**AstrBot**](https://github.com/AstrBotDevs/AstrBot) 设计的关键词监控与自动处理插件。它可以实时监控群聊消息，通过关键词或正则表达式进行识别，并自动执行**撤回消息**、**禁言用户**以及**累计违规踢出**等操作。

---

## 🚀 功能特性

* 🔍 **全量内容检测**：不仅支持普通文本检测，还支持 **JSON 卡片/分享** 消息的内容提取与监控。
* 🎭 **多模态规则**：支持按**消息类型**（文本、图片、语音、视频、文件、表情、转发消息、卡片/分享）进行拦截。
* 🕒 **时间段监控**：支持设置规则生效时间段（如深夜模式），支持跨天配置。
* 📝 **正则规则支持**：关键词支持正则表达式，匹配更灵活。
* 📈 **违规计数踢出**：支持记录用户违规次数，达到阈值后自动踢出群聊。
* 🛡️ **精细权限控制**：支持群主豁免、管理员忽略配置以及全局/规则级双层白名单。

---

## 📖 配置说明

### 1. 全局配置

| 配置项 | 类型 | 描述 |
| :--- | :--- | :--- |
| **`group_blacklist`** | `list` | 群聊黑名单。名单中的群聊不会触发任何检测。 |
| **`user_whitelist`** | `list` | 用户白名单。名单中的用户在所有群聊中都不会触发检测。 |

### 2. 检测规则配置

本插件支持两种规则模板：**关键词规则** 和 **消息类型规则**。

#### 核心配置项

| 配置项 | 类型 | 默认值 | 描述 |
| :--- | :--- | :--- | :--- |
| **`keywords`** | `list` | `[]` | (仅关键词规则) 关键词列表，支持正则表达式。 |
| **`msg_types`** | `list` | `[]` | (仅类型规则) 选择监控的消息类型（图片、视频、JSON 等）。 |
| **`time_range`** | `string` | `""` | (仅类型规则) 生效时间段。格式如 `23:00-07:00`，支持跨天。 |
| **`groups`** | `list` | `[]` | 生效群号列表。留空表示在所有非黑名单群生效。 |
| **`mute_duration`** | `string` | `"0"` | 禁言时长（秒）。支持范围（如 `30-60`）。`0` 表示不禁言，`-1` 表示不禁言且不撤回。 |
| **`reply_message`** | `list` | `[]` | 撤回后随机发送的回复提醒。 |
| **`ignore_admin`** | `bool` | `false` | 开启后，该规则将忽略管理员。 |
| **`rule_user_whitelist`** | `list` | `[]` | 规则特定用户白名单。 |
| **`rule_user_monitor_list`** | `list` | `[]` | 规则特定用户监控名单。填写后仅监控名单内用户。 |
| **`kick_threshold`** | `int` | `0` | 踢出阈值（次数）。`0` 表示不开启。 |
| **`kick_message`** | `list` | `[]` | 踢出用户后随机发送的提示消息。 |

---


## ❤️ 支持

* [AstrBot 帮助文档](https://astrbot.app)
* 如果您在使用中遇到问题，欢迎在本仓库提交 [Issue](https://github.com/Foolllll-J/astrbot_plugin_sentinel/issues)。

---

<div align="center">

**如果本插件对你有帮助，欢迎点个 ⭐ Star 支持一下！**

</div>
