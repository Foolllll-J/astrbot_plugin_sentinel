import re
import json
import random
import asyncio
from datetime import datetime
from typing import List, Set, Optional, Dict, Any
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("astrbot_plugin_sentinel", "Foolllll", "实时监控群聊消息，通过关键词或正则表达式进行识别，并自动执行撤回、禁言以及踢出等操作。", "v1.0")
class SentinelPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self._compiled_rules = []
        self._global_whitelist_set = set()
        self._group_blacklist_set = set()
        self._update_cache()

    def _update_cache(self):
        """更新配置缓存，预编译正则表达式并转换列表为集合以提高性能"""
        # 更新全局白名单和黑名单集合
        self._global_whitelist_set = {str(u) for u in self.config.get("user_whitelist", [])}
        self._group_blacklist_set = {str(g) for g in self.config.get("group_blacklist", [])}
        
        # 预编译规则
        self._compiled_rules = []
        rules = self.config.get("sentinel_rules", [])
        for i, rule in enumerate(rules):
            compiled_rule = rule.copy()
            # 预处理规则级集合
            compiled_rule["_user_whitelist_set"] = {str(u) for u in rule.get("rule_user_whitelist", [])}
            compiled_rule["_user_monitor_list_set"] = {str(u) for u in rule.get("rule_user_monitor_list", [])}
            compiled_rule["_groups_set"] = {str(g) for g in rule.get("groups", [])}
            
            # 预编译正则（针对关键词规则）
            compiled_patterns = []
            for kw in rule.get("keywords", []):
                try:
                    compiled_patterns.append(re.compile(kw))
                except re.error as e:
                    logger.error(f"[Sentinel] 规则 {i} 正则表达式语法错误: {kw}, 错误: {e}")
                    # 即使语法错误也保留字符串，后续回退到普通匹配
                    compiled_patterns.append(kw)
            compiled_rule["_compiled_patterns"] = compiled_patterns

            # 预处理消息类型（针对消息类型规则）
            compiled_rule["_msg_types_set"] = set(rule.get("msg_types", []))
            
            self._compiled_rules.append(compiled_rule)

    def _is_in_time_range(self, time_range: str) -> bool:
        """检查当前时间是否在指定的时间段内 (格式: 23:23-01:34)"""
        if not time_range:
            return True
        try:
            now = datetime.now().time()
            now_str = now.strftime("%H:%M")
            start_str, end_str = time_range.split("-")
            
            if start_str <= end_str:
                return start_str <= now_str <= end_str
            else: # 跨天
                return now_str >= start_str or now_str <= end_str
        except Exception as e:
            logger.error(f"[Sentinel] 时间段格式错误: {time_range}, 错误: {e}")
            return True # 格式错误时默认触发检测以保证安全

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=10)
    async def on_message(self, event: AstrMessageEvent):
        """处理群聊消息，进行关键词检测、撤回及禁言。"""
        raw_message = event.message_obj.raw_message
        role = raw_message.get('sender', {}).get('role', 'member')
        
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
        
        # 处理消息链组件
        messages = event.get_messages()
        for msg_seg in messages:
            seg_str = str(msg_seg)
            # 类型识别 (优先检查组件对象中是否存在 type.name，这是 AstrBot 统一的识别方式)
            seg_type = getattr(getattr(msg_seg, 'type', None), 'name', None)
            
            # 如果没有 type.name，则回退到类名识别
            if not seg_type:
                seg_type = msg_seg.__class__.__name__
            
            if seg_type in ["Plain", "Text"]:
                continue
            elif seg_type == "Image":
                msg_types.add("图片")
            elif seg_type in ["Record", "Voice"]:
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
                # 提取 JSON 内容用于关键词检测
                json_data = getattr(msg_seg, 'data', '{}')
                if isinstance(json_data, dict):
                    content_parts.append(json.dumps(json_data, ensure_ascii=False))
                else:
                    content_parts.append(str(json_data))
             
        message_to_check = " ".join(content_parts)

        # 3. 匹配规则
        for i, rule in enumerate(self._compiled_rules):
            # 时间段检查 (仅对支持 time_range 的规则生效)
            if not self._is_in_time_range(rule.get("time_range", "")):
                continue

            # 监控名单检查：如果设置了监控名单且用户不在其中，跳过此规则
            monitor_set = rule["_user_monitor_list_set"]
            if monitor_set and user_id not in monitor_set:
                continue

            # 规则白名单检查
            if user_id in rule["_user_whitelist_set"]:
                continue

            # 管理员豁免检查
            if rule.get("ignore_admin", False) and role == 'admin':
                continue

            # 群组范围检查
            target_groups = rule["_groups_set"]
            if target_groups and group_id not in target_groups:
                continue
            
            # 命中判定
            matched = False
            
            # 逻辑 A: 关键词匹配 (keyword_rule)
            if rule.get("keywords"):
                for pattern in rule["_compiled_patterns"]:
                    if isinstance(pattern, re.Pattern):
                        if pattern.search(message_to_check):
                            matched = True
                            break
                    elif isinstance(pattern, str): # 回退匹配
                        if pattern in message_to_check:
                            matched = True
                            break
            
            # 逻辑 B: 消息类型匹配 (type_rule)
            elif rule.get("msg_types"):
                rule_msg_types = rule["_msg_types_set"]
                if rule_msg_types & msg_types: # 交集不为空则匹配
                    matched = True
            
            if matched:
                await self.execute_actions(event, rule, i)
                event.stop_event()
                break

    async def execute_actions(self, event: AstrMessageEvent, rule: dict, rule_index: int):
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        message_id = event.message_obj.message_id
        
        # 1. 撤回消息
        try:
            await event.bot.api.call_action("delete_msg", message_id=message_id)
            logger.info(f"[Sentinel] 已撤回群 {group_id} 中用户 {user_id} 的违规消息: {message_id}")
        except Exception as e:
            logger.error(f"[Sentinel] 撤回消息失败: {e}。请确认 Bot 是否具有管理员权限。")

        # 2. 禁言逻辑
        mute_duration_str = str(rule.get("mute_duration", "0"))
        duration = 0
        try:
            if "-" in mute_duration_str:
                start, end = map(int, mute_duration_str.split("-"))
                duration = random.randint(start, end)
            else:
                duration = int(mute_duration_str)
        except ValueError:
            logger.error(f"[Sentinel] 禁言时长格式错误: {mute_duration_str}")
        
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
        kick_threshold = rule.get("kick_threshold", 0)
        if kick_threshold > 0:
            kv_key = f"hits:{group_id}:{user_id}:{rule_index}"
            
            # 读取计数
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
                    logger.info(f"[Sentinel] 用户 {user_id} 在群 {group_id} 命中规则 {rule_index} 达到阈值 {kick_threshold}，已踢出。")
                    
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
                logger.debug(f"[Sentinel] 用户 {user_id} 命中规则 {rule_index}，当前累计次数: {current_hits}/{kick_threshold}")

    async def terminate(self):
        pass
