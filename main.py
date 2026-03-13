import re
import json
import random
import asyncio
from datetime import datetime
from typing import List, Set, Dict, Any
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger


class SentinelPlugin(Star):
    COMMAND_RULES_KEY = "command_monitor_rules"

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self._compiled_global_rules = []
        self._compiled_rules_by_group = {}
        self._command_rules = []
        self._global_whitelist_set = set()
        self._group_blacklist_set = set()
        self._command_whitelist_set = set()
        self._observed_admin_ids = set()
        self._command_rules_lock = asyncio.Lock()
        self._warned_no_admin_targets = False
        self._update_cache()

    async def initialize(self):
        await self._load_command_rules()
        self._update_cache()

    async def _load_command_rules(self):
        data = await self.get_kv_data(self.COMMAND_RULES_KEY, [])
        if not isinstance(data, list):
            self._command_rules = []
            return

        result = []
        max_id = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            keywords = item.get("keywords", [])
            groups = item.get("groups", [])
            if not keywords or not groups:
                continue
            normalized = item.copy()
            rid = str(normalized.get("rule_id", "")).strip()
            if rid.isdigit():
                rid_num = int(rid)
                if rid_num > max_id:
                    max_id = rid_num
                normalized["rule_id"] = rid
            else:
                max_id += 1
                normalized["rule_id"] = str(max_id)
            result.append(normalized)
        self._command_rules = result

    async def _save_command_rules(self):
        await self.put_kv_data(self.COMMAND_RULES_KEY, self._command_rules)

    def _get_command_module_config(self) -> Dict[str, Any]:
        raw = self.config.get("command_module", {})
        if not isinstance(raw, dict):
            raw = {}
        return {
            "command_user_whitelist": [str(u).strip() for u in raw.get("command_user_whitelist", []) if str(u).strip()],
            "mute_duration": str(raw.get("mute_duration", "0")).strip() or "0",
            "reply_message": [str(m).strip() for m in raw.get("reply_message", []) if str(m).strip()],
            "ignore_admin": bool(raw.get("ignore_admin", False)),
            "kick_threshold": self._safe_int(raw.get("kick_threshold", 0), 0),
            "kick_message": [str(m).strip() for m in raw.get("kick_message", []) if str(m).strip()],
            "notify_creator": bool(raw.get("notify_creator", False)),
        }

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _next_command_rule_id(self) -> str:
        """生成下一个指令规则 ID（纯数字字符串）。"""
        max_id = 0
        for rule in self._command_rules:
            rid = str(rule.get("rule_id", "")).strip()
            if not rid.isdigit():
                continue
            num = int(rid)
            if num > max_id:
                max_id = num
        return str(max_id + 1)

    def _update_cache(self):
        """更新配置缓存，预编译正则表达式并转换列表为集合以提高性能"""
        self._global_whitelist_set = {str(u) for u in self.config.get("user_whitelist", [])}
        self._group_blacklist_set = {str(g) for g in self.config.get("group_blacklist", [])}

        cmd_cfg = self._get_command_module_config()
        self._command_whitelist_set = set(cmd_cfg.get("command_user_whitelist", []))

        self._compiled_global_rules = []
        self._compiled_rules_by_group = {}
        merged_rules = []

        static_rules = self.config.get("sentinel_rules", [])
        for i, rule in enumerate(static_rules):
            if not isinstance(rule, dict):
                continue
            r = rule.copy()
            r["_rule_source"] = "config"
            r["_rule_id"] = f"cfg:{i}"
            merged_rules.append(r)

        for rule in self._command_rules:
            if not isinstance(rule, dict):
                continue
            r = rule.copy()
            rid = str(r.get("rule_id", "")).strip()
            if not rid.isdigit():
                continue
            r["_rule_source"] = "command"
            r["_rule_id"] = rid
            merged_rules.append(r)

        for i, rule in enumerate(merged_rules):
            compiled_rule = rule.copy()
            compiled_rule["_order"] = i
            compiled_rule["_user_whitelist_set"] = {str(u) for u in rule.get("rule_user_whitelist", [])}
            compiled_rule["_user_monitor_list_set"] = {str(u) for u in rule.get("rule_user_monitor_list", [])}
            compiled_rule["_groups_set"] = {str(g) for g in rule.get("groups", [])}

            compiled_patterns = []
            for kw in rule.get("keywords", []):
                kw_text = str(kw)
                if compiled_rule.get("_rule_source") == "command":
                    # 指令规则关键词仅做纯文本匹配，不支持正则
                    compiled_patterns.append(kw_text)
                    continue
                try:
                    compiled_patterns.append(re.compile(kw_text))
                except re.error as e:
                    logger.error(f"[Sentinel] 规则 {i} 正则表达式语法错误: {kw_text}, 错误: {e}")
                    compiled_patterns.append(kw_text)
            compiled_rule["_compiled_patterns"] = compiled_patterns

            compiled_rule["_msg_types_set"] = set(rule.get("msg_types", []))

            groups_set = compiled_rule["_groups_set"]
            if groups_set:
                for gid in groups_set:
                    self._compiled_rules_by_group.setdefault(gid, []).append(compiled_rule)
            else:
                self._compiled_global_rules.append(compiled_rule)

    def _get_candidate_rules_for_group(self, group_id: str) -> List[dict]:
        group_rules = self._compiled_rules_by_group.get(group_id, [])
        if not group_rules:
            return self._compiled_global_rules
        if not self._compiled_global_rules:
            return group_rules

        # 线性合并两条有序规则链，保持与原始配置一致的匹配顺序
        merged = []
        global_rules = self._compiled_global_rules
        i = 0
        j = 0
        while i < len(global_rules) and j < len(group_rules):
            if global_rules[i]["_order"] <= group_rules[j]["_order"]:
                merged.append(global_rules[i])
                i += 1
            else:
                merged.append(group_rules[j])
                j += 1
        if i < len(global_rules):
            merged.extend(global_rules[i:])
        if j < len(group_rules):
            merged.extend(group_rules[j:])
        return merged

    def _resolve_effective_rule(self, rule: dict) -> dict:
        if rule.get("_rule_source") != "command":
            return rule
        cmd_cfg = self._get_command_module_config()
        effective = rule.copy()
        # 指令模块白名单用户对“指令规则”免检
        cmd_whitelist = set(cmd_cfg.get("command_user_whitelist", []))
        base_whitelist = {str(u) for u in effective.get("_user_whitelist_set", set())}
        effective["_user_whitelist_set"] = base_whitelist | cmd_whitelist
        effective["mute_duration"] = cmd_cfg["mute_duration"]
        effective["reply_message"] = cmd_cfg["reply_message"]
        effective["ignore_admin"] = cmd_cfg["ignore_admin"]
        effective["kick_threshold"] = cmd_cfg["kick_threshold"]
        effective["kick_message"] = cmd_cfg["kick_message"]
        effective["_notify_creator"] = cmd_cfg["notify_creator"]
        return effective

    def _is_in_time_range(self, time_range: str) -> bool:
        """检查当前时间是否在指定的时间段内(格式: 23:23-01:34)"""
        if not time_range:
            return True
        try:
            now = datetime.now().time()
            now_str = now.strftime("%H:%M")
            start_str, end_str = time_range.split("-")

            if start_str <= end_str:
                return start_str <= now_str <= end_str
            else:
                return now_str >= start_str or now_str <= end_str
        except Exception as e:
            logger.error(f"[Sentinel] 时间段格式错误: {time_range}, 错误: {e}")
            return True

    def _extract_json_descriptive_text(self, json_payload: Any) -> str:
        """从分享卡片 JSON 中提取适合做关键词检测的介绍性文字。"""
        descriptive_keys = {
            "title",
            "desc",
            "description",
            "prompt",
            "content",
            "text",
            "brief",
            "summary",
            "subtitle",
        }
        ignored_keys = {
            "app",
            "appid",
            "app_type",
            "bizsrc",
            "config",
            "ctime",
            "extra",
            "jumpUrl",
            "preview",
            "tagIcon",
            "token",
            "uin",
            "ver",
            "view",
        }
        texts = []
        seen = set()

        def _append_text(value: Any):
            text = str(value).strip()
            if not text or text in seen:
                return
            # 忽略 URL、纯数字和明显的机器标识，避免误伤短关键词。
            if re.match(r"^https?://", text, flags=re.IGNORECASE):
                return
            if text.isdigit():
                return
            if re.fullmatch(r"[A-Za-z0-9_\-=:/.]{16,}", text):
                return
            seen.add(text)
            texts.append(text)

        def _walk(node: Any, parent_key: str = ""):
            if isinstance(node, dict):
                for key, value in node.items():
                    key_text = str(key).strip()
                    if key_text in ignored_keys:
                        continue
                    if key_text in descriptive_keys and not isinstance(value, (dict, list)):
                        _append_text(value)
                        continue
                    _walk(value, key_text)
                return
            if isinstance(node, list):
                for item in node:
                    _walk(item, parent_key)
                return
            if parent_key in descriptive_keys:
                _append_text(node)

        parsed_payload = json_payload
        if isinstance(json_payload, str):
            raw_text = json_payload.strip()
            if raw_text:
                try:
                    parsed_payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    return raw_text
            else:
                return ""

        _walk(parsed_payload)
        return " ".join(texts)

    def _extract_at_user_ids(self, event: AstrMessageEvent) -> List[str]:
        ids = []
        seen = set()
        self_id = ""
        try:
            self_id = str(event.get_self_id() or "").strip()
        except Exception:
            self_id = ""

        def _append_if_valid(raw_id: str):
            qq = str(raw_id).strip()
            if not qq or qq == "all" or qq == self_id or qq in seen:
                return
            seen.add(qq)
            ids.append(qq)

        for seg in event.get_messages() or []:
            seg_type = getattr(getattr(seg, "type", None), "name", None) or seg.__class__.__name__
            if seg_type != "At":
                continue
            _append_if_valid(getattr(seg, "qq", ""))

        text = event.message_str or ""
        for m in re.finditer(r"\[CQ:at,qq=([^,\]]+)", text, flags=re.IGNORECASE):
            _append_if_valid(m.group(1))
        for m in re.finditer(r"@(\d{5,})", text):
            _append_if_valid(m.group(1))
        return ids

    def _extract_command_keyword(self, event: AstrMessageEvent) -> str:
        parts = (event.message_str or "").strip().split()
        if len(parts) < 2:
            return ""
        keyword = parts[1].strip()
        if keyword.startswith("@") or "[CQ:at" in keyword:
            return ""
        return keyword

    def _is_command_allowed(self, event: AstrMessageEvent) -> bool:
        try:
            if event.is_admin():
                return True
        except Exception:
            pass
        return str(event.get_sender_id()) in self._command_whitelist_set

    def _capture_admin(self, event: AstrMessageEvent, role: str):
        sender_id = str(event.get_sender_id())
        if role in {"owner", "admin"}:
            self._observed_admin_ids.add(sender_id)
            return
        try:
            if event.is_admin():
                self._observed_admin_ids.add(sender_id)
        except Exception:
            pass

    def _get_admin_targets(self) -> Set[str]:
        targets = set(self._observed_admin_ids)
        try:
            cfg = self.context.get_config()
            admin_ids = cfg.get("admins_id", [])
            if isinstance(admin_ids, list):
                targets.update({str(x).strip() for x in admin_ids if str(x).strip()})
        except Exception as e:
            logger.debug(f"[Sentinel] 读取 admins_id 失败: {e}")
        return targets

    async def _send_private_msg(self, event: AstrMessageEvent, user_ids: Set[str], message: str):
        if not message:
            return
        for uid in user_ids:
            try:
                await event.bot.api.call_action("send_private_msg", user_id=str(uid), message=message)
            except Exception as e:
                logger.error(f"[Sentinel] 私聊通知失败 user_id={uid}: {e}")

    async def _notify_for_hit(self, event: AstrMessageEvent, rule: dict, rule_id: str, duration: int):
        keywords = rule.get("keywords", [])
        msg_types = rule.get("msg_types", [])
        if keywords:
            match_desc = f"关键词: {', '.join(str(k) for k in keywords)}"
        elif msg_types:
            match_desc = f"消息类型: {', '.join(str(t) for t in msg_types)}"
        else:
            match_desc = "匹配条件: 未知"

        actions = []
        actions.append("撤回" if duration != -1 else "不撤回")
        if duration > 0:
            actions.append(f"禁言{duration}s")
        kick_threshold = self._safe_int(rule.get("kick_threshold", 0), 0)
        if kick_threshold > 0:
            actions.append(f"累计{kick_threshold}次踢出")

        text = (
            f"⚠️ 群哨兵通知\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"群号: {event.get_group_id()}\n"
            f"用户: {event.get_sender_id()}\n"
            f"{match_desc}\n"
            f"动作: {' / '.join(actions)}"
        )

        if rule.get("_rule_source") == "command":
            if not bool(rule.get("_notify_creator", False)):
                return
            creator = str(rule.get("created_by", "")).strip()
            if not creator:
                return
            await self._send_private_msg(event, {creator}, text)
            return

        if not bool(rule.get("notify_admin", False)):
            return
        admins = self._get_admin_targets()
        if not admins:
            if not self._warned_no_admin_targets:
                logger.warning(
                    "[Sentinel] notify_admin 已开启，但未找到管理员通知目标。"
                    "请检查全局配置 admins_id 或确认管理员曾在会话中发言。"
                )
                self._warned_no_admin_targets = True
            return
        self._warned_no_admin_targets = False
        await self._send_private_msg(event, admins, text)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=10)
    async def on_message(self, event: AstrMessageEvent):
        """处理群聊消息，进行关键词检测、撤回及禁言。"""
        raw_message = event.message_obj.raw_message
        role = raw_message.get('sender', {}).get('role', 'member')
        self._capture_admin(event, role)

        # 1. 基础过滤
        if role == 'owner':
            return

        user_id = str(event.get_sender_id())
        if user_id in self._global_whitelist_set:
            return

        group_id = str(event.get_group_id())
        if group_id in self._group_blacklist_set:
            return

        # 2. 构建待检测文本与类型
        content_parts = [event.message_str]
        msg_types = set()

        messages = event.get_messages()
        for msg_seg in messages:
            seg_type = getattr(getattr(msg_seg, 'type', None), 'name', None)
            if not seg_type:
                seg_type = msg_seg.__class__.__name__

            if seg_type in ["Plain"]:
                msg_types.add("文本")
                continue
            elif seg_type == "Image":
                msg_types.add("图片")
            elif seg_type in ["Record"]:
                msg_types.add("语音")
            elif seg_type == "Video":
                msg_types.add("视频")
            elif seg_type == "File":
                msg_types.add("文件")
            elif seg_type == "Face":
                msg_types.add("表情")
            elif seg_type == "Forward":
                msg_types.add("转发消息")
            elif seg_type == "Json":
                msg_types.add("卡片/分享")
                json_data = getattr(msg_seg, 'data', '{}')
                descriptive_text = self._extract_json_descriptive_text(json_data)
                if descriptive_text:
                    content_parts.append(descriptive_text)

        message_to_check = " ".join(content_parts)

        # 3. 匹配规则
        candidate_rules = self._get_candidate_rules_for_group(group_id)
        for i, raw_rule in enumerate(candidate_rules):
            rule = self._resolve_effective_rule(raw_rule)

            if not self._is_in_time_range(rule.get("time_range", "")):
                continue

            monitor_set = rule["_user_monitor_list_set"]
            if monitor_set and user_id not in monitor_set:
                continue

            if user_id in rule["_user_whitelist_set"]:
                continue

            if rule.get("ignore_admin", False) and role == 'admin':
                continue

            target_groups = rule["_groups_set"]
            if target_groups and group_id not in target_groups:
                continue

            matched = False
            if rule.get("keywords"):
                for pattern in rule["_compiled_patterns"]:
                    if isinstance(pattern, re.Pattern):
                        if pattern.search(message_to_check):
                            matched = True
                            break
                    elif isinstance(pattern, str):
                        if pattern in message_to_check:
                            matched = True
                            break
            elif rule.get("msg_types"):
                rule_msg_types = rule["_msg_types_set"]
                if rule_msg_types & msg_types:
                    matched = True

            if matched:
                rule_id = str(rule.get("_rule_id", i))
                await self.execute_actions(event, rule, rule_id)
                event.stop_event()
                break

    async def execute_actions(self, event: AstrMessageEvent, rule: dict, rule_id: str):
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        message_id = event.message_obj.message_id

        # 解析禁言时长
        mute_duration_str = str(rule.get("mute_duration", "0")).strip()
        duration = 0
        try:
            if "-" in mute_duration_str and not mute_duration_str.startswith("-"):
                start, end = map(int, mute_duration_str.split("-"))
                duration = random.randint(min(start, end), max(start, end))
            else:
                duration = int(float(mute_duration_str))
        except (ValueError, TypeError):
            logger.error(f"[Sentinel] 禁言时长格式错误: {mute_duration_str}")

        # 1. 撤回消息 (-1 表示不撤回也不禁言)
        if duration != -1:
            try:
                await event.bot.api.call_action("delete_msg", message_id=message_id)
                logger.info(f"[Sentinel] 已撤回群 {group_id} 中用户 {user_id} 的违规消息 {message_id}")
            except Exception as e:
                logger.error(f"[Sentinel] 撤回消息失败: {e}。请确认 Bot 是否具有管理员权限。")

        # 2. 禁言逻辑
        if duration > 0:
            try:
                await event.bot.api.call_action(
                    "set_group_ban",
                    group_id=int(group_id),
                    user_id=int(user_id),
                    duration=duration
                )
                logger.info(f"[Sentinel] 已禁言群 {group_id} 中用户 {user_id}，时长: {duration}秒")
            except Exception as e:
                logger.error(f"[Sentinel] 禁言失败: {e}。请确认 Bot 是否具有管理员权限。")

        # 3. 发送回复
        reply_messages = rule.get("reply_message", [])
        if reply_messages:
            reply_text = random.choice(reply_messages)
            if reply_text:
                await asyncio.sleep(0.5)
                await event.send(event.plain_result(reply_text))

        # 4. 踢人与计数逻辑
        kick_threshold = self._safe_int(rule.get("kick_threshold", 0), 0)
        if kick_threshold > 0:
            kv_key = f"hits:{group_id}:{user_id}:{rule_id}"
            try:
                data = await self.get_kv_data(kv_key, 0)
                current_hits = int(data)
            except (ValueError, TypeError):
                current_hits = 0

            current_hits += 1

            if current_hits >= kick_threshold:
                try:
                    await event.bot.api.call_action(
                        "set_group_kick",
                        group_id=int(group_id),
                        user_id=int(user_id),
                        reject_add_request=False
                    )
                    logger.info(
                        f"[Sentinel] 用户 {user_id} 在群 {group_id} 命中规则 {rule_id} 达到阈值 {kick_threshold}，已踢出。"
                    )

                    kick_messages = rule.get("kick_message", [])
                    if kick_messages:
                        kick_text = random.choice(kick_messages)
                        if kick_text:
                            await event.send(event.plain_result(kick_text))

                    await self.delete_kv_data(kv_key)
                except Exception as e:
                    logger.error(f"[Sentinel] 踢人失败: {e}。请确认 Bot 是否具有管理员权限。")
            else:
                await self.put_kv_data(kv_key, current_hits)
                logger.debug(
                    f"[Sentinel] 用户 {user_id} 命中规则 {rule_id}，当前累计次数: {current_hits}/{kick_threshold}"
                )

        await self._notify_for_hit(event, rule, rule_id, duration)

    @filter.command("监控")
    async def add_monitor_by_command(self, event: AstrMessageEvent):
        """新增指令规则。
        用法: /监控 <关键词> [@某人 ...]
        """
        if not self._is_command_allowed(event):
            yield event.plain_result("❌ 仅管理员或指令白名单用户可使用该命令。")
            return

        group_id = str(event.get_group_id() or "").strip()
        if not group_id:
            yield event.plain_result("❌ 请在群聊中使用该命令。")
            return

        keyword = self._extract_command_keyword(event)
        if not keyword:
            yield event.plain_result("❌ 用法：/监控 <关键词> [@某人 ...]")
            return
        if keyword.isdigit():
            yield event.plain_result(
                "❌ 指令添加不允许纯数字关键词；如需纯数字关键词，请在配置页面添加。"
            )
            return

        target_user_ids = self._extract_at_user_ids(event)
        target_set = set(target_user_ids)

        duplicate_exists = False
        async with self._command_rules_lock:
            for existing in self._command_rules:
                ex_keywords = [str(k) for k in existing.get("keywords", [])]
                ex_groups = {str(g) for g in existing.get("groups", [])}
                ex_monitors = {str(u) for u in existing.get("rule_user_monitor_list", [])}
                if keyword in ex_keywords and group_id in ex_groups and ex_monitors == target_set:
                    duplicate_exists = True
                    break

            if not duplicate_exists:
                new_rule = {
                    "rule_id": self._next_command_rule_id(),
                    "keywords": [keyword],
                    "groups": [group_id],
                    "rule_user_monitor_list": target_user_ids,
                    "rule_user_whitelist": [],
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "created_by": str(event.get_sender_id()),
                }
                self._command_rules.append(new_rule)
                await self._save_command_rules()
                self._update_cache()

        if duplicate_exists:
            yield event.plain_result("ℹ️ 已存在相同监控规则。")
            return

        target_desc = "全体成员" if not target_user_ids else ", ".join(target_user_ids)
        yield event.plain_result(
            f"✅ 已添加监控规则\n规则ID: {new_rule['rule_id']}\n关键词: {keyword}\n目标用户: {target_desc}\n群号: {group_id}"
        )

    @filter.command("取消监控")
    async def remove_monitor_by_command(self, event: AstrMessageEvent):
        """删除指令规则。
        用法: /取消监控 <rule_id> 或 /取消监控 [关键词] @某人
        """
        if not self._is_command_allowed(event):
            yield event.plain_result("❌ 仅管理员或指令白名单用户可使用该命令。")
            return

        group_id = str(event.get_group_id() or "").strip()
        if not group_id:
            yield event.plain_result("❌ 请在群聊中使用该命令。")
            return

        parts = (event.message_str or "").strip().split()
        arg = parts[1].strip() if len(parts) > 1 else ""
        at_user_ids = self._extract_at_user_ids(event)

        if not arg and not at_user_ids:
            yield event.plain_result("❌ 用法：/取消监控 <rule_id> 或 /取消监控 [关键词] @某人")
            return

        # 1) 按 rule_id 删除（优先）
        if arg:
            removed_by_id = None
            async with self._command_rules_lock:
                group_rule_ids = {
                    str(r.get("rule_id", "")).strip()
                    for r in self._command_rules
                    if group_id in {str(g) for g in r.get("groups", [])}
                }
                if arg in group_rule_ids:
                    retained = []
                    removed = 0
                    for rule in self._command_rules:
                        rid = str(rule.get("rule_id", "")).strip()
                        groups = {str(g) for g in rule.get("groups", [])}
                        if rid == arg and group_id in groups:
                            removed += 1
                            continue
                        retained.append(rule)
                    self._command_rules = retained
                    await self._save_command_rules()
                    self._update_cache()
                    removed_by_id = removed
            if removed_by_id is not None:
                yield event.plain_result(f"✅ 已按规则ID删除 {removed_by_id} 条监控规则。")
                return

        # 2) 只 @ 用户：仅移除目标用户的监控，不影响同规则中的其他对象
        user_only_mode = bool(at_user_ids) and (not arg or arg.startswith("@") or "[CQ:at" in arg)
        if user_only_mode:
            targets = set(at_user_ids)
            changed = 0
            removed = 0
            async with self._command_rules_lock:
                retained = []
                for rule in self._command_rules:
                    groups = {str(g) for g in rule.get("groups", [])}
                    if group_id not in groups:
                        retained.append(rule)
                        continue

                    monitor_list = [str(u) for u in rule.get("rule_user_monitor_list", [])]
                    monitor_set = set(monitor_list)

                    # 仅处理指定监控用户的规则；全群规则不受影响
                    if monitor_set:
                        if not (monitor_set & targets):
                            retained.append(rule)
                            continue
                        new_monitor_list = [u for u in monitor_list if u not in targets]
                        if not new_monitor_list:
                            removed += 1
                            continue
                        if len(new_monitor_list) != len(monitor_list):
                            rule = rule.copy()
                            rule["rule_user_monitor_list"] = new_monitor_list
                            changed += 1
                        retained.append(rule)
                        continue

                    # 全群规则：平行存在，不参与“只 @ 用户”删除
                    retained.append(rule)

                if changed != 0 or removed != 0:
                    self._command_rules = retained
                    await self._save_command_rules()
                    self._update_cache()
            if changed == 0 and removed == 0:
                yield event.plain_result("ℹ️ 未找到与该用户相关的监控规则。")
                return
            if removed > 0:
                yield event.plain_result(
                    f"✅ 已更新 {changed} 条规则，并删除 {removed} 条仅面向目标用户的规则。"
                )
            else:
                yield event.plain_result(f"✅ 已更新 {changed} 条与目标用户相关的监控规则。")
            return

        # 3) 关键词 + 可选 @ 用户
        keyword = arg
        targets = set(at_user_ids)
        removed = 0
        changed = 0
        async with self._command_rules_lock:
            retained = []
            for rule in self._command_rules:
                rule_keywords = [str(k) for k in rule.get("keywords", [])]
                groups = {str(g) for g in rule.get("groups", [])}

                if keyword in rule_keywords and group_id in groups:
                    # 带 @ 时：仅移除目标用户，不影响同规则中的其他对象，也不影响全群规则
                    if targets:
                        monitor_list = [str(u) for u in rule.get("rule_user_monitor_list", [])]
                        monitors = set(monitor_list)
                        if not monitors:
                            retained.append(rule)
                            continue
                        if not (monitors & targets):
                            retained.append(rule)
                            continue

                        new_monitor_list = [u for u in monitor_list if u not in targets]
                        if not new_monitor_list:
                            removed += 1
                            continue
                        if len(new_monitor_list) != len(monitor_list):
                            rule = rule.copy()
                            rule["rule_user_monitor_list"] = new_monitor_list
                            changed += 1
                        retained.append(rule)
                        continue

                    # 不带 @ 时：按关键词删除匹配规则
                    removed += 1
                    continue
                retained.append(rule)

            if removed > 0 or changed > 0:
                self._command_rules = retained
                await self._save_command_rules()
                self._update_cache()

        if removed == 0 and changed == 0:
            yield event.plain_result("ℹ️ 未找到匹配的指令监控规则。")
            return

        if targets:
            if removed > 0:
                yield event.plain_result(
                    f"✅ 已更新 {changed} 条规则，并删除 {removed} 条仅面向目标用户的规则。"
                )
            else:
                yield event.plain_result(f"✅ 已更新 {changed} 条匹配监控规则。")
            return

        yield event.plain_result(f"✅ 已删除 {removed} 条匹配监控规则。")
        return

    @filter.command("监控列表")
    async def list_monitor_by_command(self, event: AstrMessageEvent):
        """查看当前群通过指令创建的监控规则列表。"""
        if not self._is_command_allowed(event):
            yield event.plain_result("❌ 仅管理员或指令白名单用户可使用该命令。")
            return

        group_id = str(event.get_group_id() or "").strip()
        if not group_id:
            yield event.plain_result("❌ 请在群聊中使用该命令。")
            return

        async with self._command_rules_lock:
            group_rules = []
            for rule in self._command_rules:
                groups = {str(g) for g in rule.get("groups", [])}
                if group_id in groups:
                    group_rules.append(rule)

        if not group_rules:
            yield event.plain_result("ℹ️ 当前群暂无通过指令添加的监控规则。")
            return

        lines = [f"📋 当前群指令监控规则（{len(group_rules)}条）"]
        for rule in group_rules:
            rule_id = str(rule.get("rule_id", "-"))
            keyword = ", ".join(str(k) for k in rule.get("keywords", [])) or "-"
            target = ", ".join(str(u) for u in rule.get("rule_user_monitor_list", [])) or "全体成员"
            creator = str(rule.get("created_by", "-"))
            lines.extend(
                [
                    f"ID: {rule_id}",
                    f"关键词: {keyword}",
                    f"目标: {target}",
                    f"创建者: {creator}",
                    "",
                ]
            )
        if lines and lines[-1] == "":
            lines.pop()
        yield event.plain_result("\n".join(lines))

    async def terminate(self):
        pass
