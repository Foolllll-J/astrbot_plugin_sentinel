import re
import random
import asyncio
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.platform import MessageType

@register("astrbot_plugin_sentinel", "Foolllll", "检测群聊中消息是否出现关键词然后撤回加禁言", "v0.1.0")
class SentinelPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

    @filter.event_message_type(filter.EventMessageType.ALL, priority=10)
    async def on_message(self, event: AstrMessageEvent):
        # 仅处理群聊消息
        if event.get_message_type() != MessageType.GROUP_MESSAGE:
            return

        group_id = str(event.get_group_id())
        
        # 检查黑名单
        blacklist = self.config.get("group_blacklist", [])
        if group_id in [str(g) for g in blacklist]:
            return

        message_str = event.message_str
        rules = self.config.get("sentinel_rules", [])
        
        for rule in rules:
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
                await self.execute_actions(event, rule)
                event.stop_event()
                break

    async def execute_actions(self, event: AstrMessageEvent, rule: dict):
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        message_id = event.message_obj.message_id
        
        # 1. 撤回消息
        try:
            await event.bot.api.call_action("delete_msg", message_id=message_id)
            logger.info(f"[Sentinel] 已撤回群 {group_id} 中用户 {user_id} 的违规消息: {message_id}")
        except Exception as e:
            logger.error(f"[Sentinel] 撤回消息失败: {e}")

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
                logger.error(f"[Sentinel] 禁言失败: {e}")

        # 3. 发送回复提醒
        reply_message = rule.get("reply_message", "")
        if reply_message:
            await asyncio.sleep(0.5)
            await event.send(event.plain_result(reply_message))

    async def terminate(self):
        pass
