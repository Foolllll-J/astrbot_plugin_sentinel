import re
import json
import random
import asyncio
import html
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.platform import MessageType

@register("astrbot_plugin_sentinel", "Foolllll", "实时监控群聊消息，通过关键词或正则表达式进行识别，并自动执行撤回、禁言以及踢出等操作。", "v1.0")
class SentinelPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

    def _extract_text_from_json(self, json_str: str) -> str:
        """从 JSON 消息中提取所有可能的文本内容"""
        texts = []
        try:
            # 处理可能的 HTML 实体转义 (如 &#44;)
            json_str = html.unescape(json_str)
            data = json.loads(json_str)
            
            # 递归提取所有字符串值
            def walk(obj):
                if isinstance(obj, dict):
                    for v in obj.values():
                        walk(v)
                elif isinstance(obj, list):
                    for item in obj:
                        walk(item)
                elif isinstance(obj, str):
                    texts.append(obj)
            
            walk(data)
        except Exception:
            pass
            
        return " ".join(texts)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=10)
    async def on_message(self, event: AstrMessageEvent):
        """处理群聊消息，进行关键词检测、撤回及禁言"""
        # 如果是群主触发的消息，直接忽略
        role = event.message_obj.raw_message.get('sender', {}).get('role')
        if role == 'owner':
            return

        user_id = str(event.get_sender_id())
        
        # 检查全局用户白名单
        global_whitelist = self.config.get("user_whitelist", [])
        if user_id in [str(u) for u in global_whitelist]:
            return

        group_id = str(event.get_group_id())
        
        # 检查群聊黑名单
        blacklist = self.config.get("group_blacklist", [])
        if group_id in [str(g) for g in blacklist]:
            return

        # 收集待检测文本：普通文本 + 消息组件字符串
        message_str = event.message_str
        
        # 处理消息链中的组件（如 JSON/卡片）
        messages = event.get_messages()
        for msg_seg in messages:
            seg_str = str(msg_seg)
            # 只要组件字符串表示包含 Json 字样，就提取其内容
            if "json" in seg_str.lower():
                message_str += " " + seg_str

        rules = self.config.get("sentinel_rules", [])
        
        for i, rule in enumerate(rules):
            # 检查规则级用户白名单
            rule_whitelist = rule.get("rule_user_whitelist", [])
            if user_id in [str(u) for u in rule_whitelist]:
                continue

            # 检查管理员豁免
            if rule.get("ignore_admin", False) and role == 'admin':
                continue

            # 检查群组限制
            target_groups = rule.get("groups", [])
            if target_groups and group_id not in [str(g) for g in target_groups]:
                continue
            
            # 检查关键词
            keywords = rule.get("keywords", [])
            matched = False
            for kw in keywords:
                try:
                    if re.search(kw, message_str):
                        matched = True
                        break
                except re.error as e:
                    logger.error(f"[Sentinel] 正则表达式错误: {kw}, 错误: {e}")
                    # 如果正则解析失败，回退到普通字符串匹配
                    if kw in message_str:
                        matched = True
                        break
            
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

        # 2. 禁言
        mute_duration_str = str(rule.get("mute_duration", "0"))
        duration = 0
        if "-" in mute_duration_str:
            try:
                start, end = map(int, mute_duration_str.split("-"))
                duration = random.randint(start, end)
            except ValueError:
                logger.error(f"[Sentinel] 禁言时长格式错误: {mute_duration_str}")
        else:
            try:
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

        # 3. 发送回复提醒
        reply_message = rule.get("reply_message", "")
        if reply_message:
            await asyncio.sleep(0.5)
            await event.send(event.plain_result(reply_message))

        # 4. 踢人逻辑
        kick_threshold = rule.get("kick_threshold", 0)
        if kick_threshold > 0:
            # 存储 key 格式: hits:{group_id}:{user_id}:{rule_index}
            kv_key = f"hits:{group_id}:{user_id}:{rule_index}"
            current_hits = await self.get_kv_data(kv_key, 0)
            current_hits += 1
            
            if current_hits >= kick_threshold:
                try:
                    # 执行踢人
                    await event.bot.api.call_action(
                        "set_group_kick",
                        group_id=int(group_id),
                        user_id=int(user_id),
                        reject_add_request=False
                    )
                    logger.info(f"[Sentinel] 用户 {user_id} 在群 {group_id} 命中规则 {rule_index} 达到阈值 {kick_threshold}，已踢出。")
                    
                    # 发送踢人消息
                    kick_msg = rule.get("kick_message", "")
                    if kick_msg:
                        await event.send(event.plain_result(kick_msg))
                    
                    # 清除计数
                    await self.delete_kv_data(kv_key)
                except Exception as e:
                    logger.error(f"[Sentinel] 踢人失败: {e}。请确认 Bot 是否具有管理员权限。")
            else:
                # 更新计数
                await self.put_kv_data(kv_key, current_hits)
                logger.debug(f"[Sentinel] 用户 {user_id} 命中规则 {rule_index}，当前累计次数: {current_hits}/{kick_threshold}")

    async def terminate(self):
        pass
