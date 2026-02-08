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

本插件采用模板化配置，支持为不同场景创建多条规则：

| 配置项 | 类型 | 默认值 | 描述 |
| :--- | :--- | :--- | :--- |
| **`keywords`** | `list` | `[]` | 关键词列表，支持正则表达式。 |
| **`groups`** | `list` | `[]` | 生效群号列表。留空表示在所有非黑名单群生效。 |
| **`mute_duration`** | `string` | `"0"` | 禁言时长（秒）。支持固定数字或范围（如 `30-60` 随机禁言）。`0` 表示不禁言。 |
| **`reply_message`** | `list` | `[]` | 撤回后发送的回复提醒。若填写多个，将从中随机选取一条。留空表示不回复。 |
| **`ignore_admin`** | `bool` | `false` | 开启后，该规则将忽略管理员。 |
| **`rule_user_whitelist`** | `list` | `[]` | 规则特定用户白名单，仅对本条规则生效。 |
| **`rule_user_monitor_list`** | `list` | `[]` | 规则特定用户监控名单。如果填写，则**仅监控**名单中的用户，其他人不触发规则。留空表示监控所有人。 |
| **`kick_threshold`** | `int` | `0` | 踢出阈值（次数）。累计命中该规则 N 次后踢出。`0` 表示不开启。 |
| **`kick_message`** | `list` | `[]` | 踢出用户后的提示消息。若填写多个，将从中随机选取一条。留空表示不发送。 |

---


## ❤️ 支持

* [AstrBot 帮助文档](https://astrbot.app)
* 如果您在使用中遇到问题，欢迎在本仓库提交 [Issue](https://github.com/Foolllll-J/astrbot_plugin_sentinel/issues)。

---

<div align="center">

**如果本插件对你有帮助，欢迎点个 ⭐ Star 支持一下！**

</div>
