import json
import re
from datetime import datetime
from typing import Any, Callable, List, Set


def extract_json_descriptive_text(json_payload: Any) -> str:
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


def extract_at_user_ids(event: Any) -> List[str]:
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


def extract_command_keyword(event: Any) -> str:
    parts = (event.message_str or "").strip().split()
    if len(parts) < 2:
        return ""
    keyword = parts[1].strip()
    if keyword.startswith("@") or "[CQ:at" in keyword:
        return ""
    return keyword


def build_template_context(event: Any) -> dict:
    now = datetime.now()
    try:
        sender_name = str(event.get_sender_name() or "").strip()
    except Exception:
        sender_name = ""
    return {
        "id": str(event.get_sender_id() or ""),
        "name": sender_name,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
    }


def render_template_text(event: Any, text: str) -> str:
    if not text:
        return text
    context = build_template_context(event)
    pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    return pattern.sub(lambda m: str(context.get(m.group(1), m.group(0))), text)


async def get_group_admin_targets(event: Any, logger: Any) -> Set[str]:
    """实时获取群组管理员列表"""
    try:
        group_id = event.get_group_id()
        member_list = await event.bot.api.call_action("get_group_member_list", group_id=group_id)

        self_id = str(event.get_self_id() or "").strip()
        admin_ids: Set[str] = set()
        for member in member_list:
            role = member.get("role", "")
            user_id = str(member.get("user_id", "")).strip()
            if role in ["admin", "owner"] and user_id and user_id != self_id:
                admin_ids.add(user_id)

        logger.debug(f"[Sentinel] 群 {group_id} 的管理员列表: {admin_ids}")
        return admin_ids
    except Exception as e:
        logger.error(f"[Sentinel] 获取群管理员列表失败: {e}")
        return set()


def get_bot_admin_targets(context: Any, logger: Any) -> Set[str]:
    """获取Bot全局管理员列表，严格过滤QQ号格式"""
    try:
        cfg = context.get_config()
        admin_ids = cfg.get("admins_id", [])
        if isinstance(admin_ids, list):
            valid_qq_ids = {
                str(x).strip()
                for x in admin_ids
                if str(x).strip().isdigit() and 5 <= len(str(x).strip()) <= 15
            }
            invalid_ids = {str(x).strip() for x in admin_ids if str(x).strip()} - valid_qq_ids
            if invalid_ids:
                logger.warning(f"[Sentinel] 过滤了无效的Bot管理员ID: {', '.join(invalid_ids)}")
            return valid_qq_ids
    except Exception as e:
        logger.debug(f"[Sentinel] 读取 admins_id 失败: {e}")
    return set()


async def send_private_msg(event: Any, user_ids: Set[str], message: str, logger: Any):
    if not message:
        return
    for uid in user_ids:
        try:
            await event.bot.api.call_action("send_private_msg", user_id=str(uid), message=message)
        except Exception as e:
            error_msg = str(e)
            if "请先添加对方为好友" in error_msg:
                logger.warning(f"[Sentinel] 私聊通知失败 user_id={uid}: 未添加Bot为好友")
            elif "无法获取用户信息" in error_msg:
                logger.warning(f"[Sentinel] 私聊通知失败 user_id={uid}: 无法获取用户信息")
            else:
                logger.error(f"[Sentinel] 私聊通知失败 user_id={uid}: {error_msg[:100]}")


async def notify_for_hit(
    event: Any,
    rule: dict,
    duration: int,
    *,
    context: Any,
    safe_int: Callable[[Any, int], int],
    warned_no_admin_targets: bool,
    logger: Any,
) -> bool:
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
    kick_threshold = safe_int(rule.get("kick_threshold", 0), 0)
    if kick_threshold > 0:
        actions.append(f"累计{kick_threshold}次踢出")

    sender_id = str(event.get_sender_id() or "")
    try:
        sender_name = str(event.get_sender_name() or "").strip()
    except Exception:
        sender_name = ""
    user_line = f"用户: {sender_name} ({sender_id})" if sender_name else f"用户: {sender_id}"
    text = (
        f"⚠️ 群哨兵通知\n"
        f"群号: {event.get_group_id()}\n"
        f"{user_line}\n"
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{match_desc}\n"
        f"动作: {' / '.join(actions)}"
    )

    if rule.get("_rule_source") == "command":
        if not bool(rule.get("_notify_creator", False)):
            return warned_no_admin_targets
        creator = str(rule.get("created_by", "")).strip()
        if not creator:
            return warned_no_admin_targets
        await send_private_msg(event, {creator}, text, logger)
        return warned_no_admin_targets

    notify_group_admin = bool(rule.get("notify_group_admin", False))
    notify_bot_admin = bool(rule.get("notify_bot_admin", False))
    if not notify_group_admin and not notify_bot_admin:
        return warned_no_admin_targets

    group_admins = await get_group_admin_targets(event, logger) if notify_group_admin else set()
    bot_admins = get_bot_admin_targets(context, logger) if notify_bot_admin else set()
    all_targets = group_admins | bot_admins

    if not all_targets:
        if notify_bot_admin and not warned_no_admin_targets:
            logger.warning(
                "[Sentinel] notify_bot_admin 已开启，但未找到有效的Bot管理员通知目标。"
                "请检查全局配置 admins_id 中是否包含有效的QQ号。"
            )
            return True
        return warned_no_admin_targets

    await send_private_msg(event, all_targets, text, logger)
    return False
