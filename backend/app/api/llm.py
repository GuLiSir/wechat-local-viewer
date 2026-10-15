from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import json
import asyncio
import os
from ..db import get_connection
from ..llm.openai_compat import OpenAICompatClient
from ..models import LLMConfig, LLMChatRequest
from ..parsers.sender_resolver import resolve_display_name
from ..parsers.chatroom_alias import get_chatroom_alias, load_chatroom_aliases

router = APIRouter()

default_config = LLMConfig(base_url="", api_key="", model="")


@router.get("/config", response_model=LLMConfig)
async def get_llm_config():
    """获取 LLM 配置（从环境变量）"""
    import os
    return LLMConfig(
        base_url=os.getenv("LLM_BASE_URL", ""),
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", ""),
    )


@router.post("/config")
async def set_llm_config(config: LLMConfig):
    """设置 LLM 配置（仅内存缓存）"""
    global default_config
    default_config = config
    return {"status": "success"}


def _env_int(key: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(key) or default))
    except ValueError:
        return default


# 非文本占位消息不参与 AI 分析（图片/视频等对话题提炼无价值，还占预算）
_SKIP_CONTENT_PREFIXES = (
    "[图片]", "[视频]", "[表情]", "[动画表情]", "[语音]", "[文件]", "[位置]", "[音乐]",
)


def _is_analyzable(content: str | None) -> bool:
    if not content:
        return False
    c = content.strip()
    if not c or c == "[非文本消息]":
        return False
    return not any(c.startswith(p) for p in _SKIP_CONTENT_PREFIXES)


@router.post("/chat")
async def chat(request: LLMChatRequest):
    """LLM 流式聊天

    配置优先级：请求体自带（前端设置面板保存的）> 后端内存缓存 > 环境变量（含 .env）。
    分析窗口：单批上限 LLM_CONTEXT_LIMIT（默认 500）；超过则按批分析后汇总，
    总条数上限 LLM_MAX_MESSAGES（默认 10000，取最近 N 条）。
    """
    if not request.session:
        raise HTTPException(status_code=400, detail="缺少会话参数")

    max_messages = _env_int("LLM_MAX_MESSAGES", 10000)
    # 输出预算：推理模型的思考也计入 max_tokens，过小会导致长报告被截断
    max_out = _env_int("LLM_MAX_TOKENS", 16000)
    # 输入预算：按模型上下文窗口自动计算每批口径（保守估算 1 字符 ≈ 1 token，
    # 预留系统提示/用户问题的余量），超过预算自动分批分析后汇总
    context_tokens = _env_int("LLM_CONTEXT_TOKENS", 200000)
    input_budget = max(5000, context_tokens - max_out - 8000)

    lines = _collect_messages(request, limit=max_messages)
    if not lines:
        raise HTTPException(status_code=400, detail="没有找到相关消息")

    base_url = request.base_url or default_config.base_url or os.getenv("LLM_BASE_URL", "")
    api_key = request.api_key or default_config.api_key or os.getenv("LLM_API_KEY", "")
    model = request.model or default_config.model or os.getenv("LLM_MODEL", "")

    if not base_url or not model:
        raise HTTPException(
            status_code=400,
            detail="LLM 未配置：请在页面右上角设置里填写 Base URL / API Key / Model（支持 OpenAI / DeepSeek / Ollama 等兼容协议）",
        )

    client = OpenAICompatClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
    )

    system_prompt = (
        "你是一个微信聊天记录分析助手。请根据提供的聊天记录回答用户的问题。"
        "如果聊天记录不足以回答问题，请明确说明。回答要简洁、准确、客观。"
    )

    total_chars = sum(len(x) + 1 for x in lines)
    if total_chars <= input_budget:
        # 单次分析
        messages_text = "\n".join(lines)
        llm_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"聊天记录：\n{messages_text}\n\n用户问题：{request.prompt}"},
        ]
        return StreamingResponse(
            _stream_response(client, llm_messages, max_out),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # 超过输入预算 → 按预算自动分批（批次大小随消息长度动态变化）
    batches: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for line in lines:
        seg = len(line) + 1
        if cur and cur_len + seg > input_budget:
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += seg
    if cur:
        batches.append(cur)
    return StreamingResponse(
        _stream_batched(client, batches, request.prompt, system_prompt, max_out),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _collect_messages(request: LLMChatRequest, limit: int = 10000) -> list[str]:
    """收集消息内容，返回按时间正序的文本行列表。

    limit 为取最近 N 条的窗口上限（message_ids 指定时不受限制）。
    """
    load_chatroom_aliases()
    conn = get_connection()
    try:
        messages = []

        if request.message_ids and len(request.message_ids) > 0:
            placeholders = ','.join(['?' for _ in request.message_ids])
            query = f"""
                SELECT create_time, sender_username, sender_display_name, content, is_self, session_username
                FROM messages
                WHERE id IN ({placeholders})
                ORDER BY create_time
            """
            rows = conn.execute(query, request.message_ids).fetchall()
        else:
            query = """
                SELECT create_time, sender_username, sender_display_name, content, is_self, session_username
                FROM messages
                WHERE session_username = ?
                ORDER BY create_time DESC
                LIMIT ?
            """
            rows = conn.execute(query, [request.session, limit]).fetchall()
            rows = list(reversed(rows))

        for row in rows:
            content = row['content']
            # 图片/视频等非文本消息不参与分析
            if not _is_analyzable(content):
                continue
            sender = "我" if row['is_self'] == 1 else (
                (row['session_username'].endswith('@chatroom') or '@openim' in row['session_username'])
                and get_chatroom_alias(row['session_username'], row['sender_username'])
                or resolve_display_name(row['sender_username'] or '')
                or row['sender_display_name']
                or "未知"
            )
            import datetime
            dt = datetime.datetime.fromtimestamp(row['create_time'] / 1000)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
            messages.append(f"[{time_str}] {sender}: {content}")

        return messages
    finally:
        conn.close()


async def _stream_response(client: OpenAICompatClient, messages: list, max_tokens: int = 8000):
    """流式响应生成器（SSE 格式）"""
    try:
        yield f"data: {json.dumps({'type': 'start'})}\n\n"
        for chunk in client.stream(messages, max_tokens=max_tokens):
            if chunk:
                yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)
        yield f"data: {json.dumps({'type': 'end'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _stream_batched(client: OpenAICompatClient, batches: list[list[str]], prompt: str, system_prompt: str, max_out: int = 16000):
    """分批分析后汇总（SSE）。

    先逐批产出中间分析（progress 事件同步进度），再流式输出汇总结果。
    批次调用走线程池，避免长时间阻塞事件循环。
    """
    n = len(batches)
    covered = sum(len(b) for b in batches)
    try:
        yield _sse({'type': 'progress', 'content': f'共 {covered} 条消息，超过单批上限，将分 {n} 批分析后汇总…'})
        partials = []
        for i, batch in enumerate(batches, 1):
            yield _sse({'type': 'progress', 'content': f'正在分析第 {i}/{n} 批（{len(batch)} 条消息）…'})
            text = "\n".join(batch)
            batch_messages = [
                {"role": "system", "content": (
                    "你是一个微信聊天记录分析助手。下面是一段聊天记录（分批片段）。"
                    "请提炼其中的主要话题，展现各方的论点、观点与分歧（不要写成摘要）。"
                    "保留发言人名字。用要点形式，输出控制在 800 字以内。"
                )},
                {"role": "user", "content": f"聊天记录片段：\n{text}\n\n任务：{prompt}"},
            ]
            partial = await asyncio.to_thread(client.complete, batch_messages, 10000, 300.0)
            if partial and partial.strip():
                partials.append(f"【第 {i} 批（{len(batch)} 条消息）】\n{partial.strip()}")
            yield _sse({'type': 'progress', 'content': f'第 {i}/{n} 批完成'})

        if not partials:
            yield _sse({'type': 'error', 'error': '分批分析未返回任何内容，请检查模型配置或重试'})
            return

        yield _sse({'type': 'progress', 'content': f'正在汇总 {n} 批分析结果…'})
        merge_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"以下是对同一份聊天记录分 {n} 批分析的结果。请合并为一份完整的分析报告："
                "按话题归类、去重合并，保留发言人及其观点，可标注话题间的关联；"
                "不要写成摘要，聚焦论点与观点；最后用一两句话给出总体判断。\n\n"
                + "\n\n".join(partials)
                + f"\n\n用户原始要求：{prompt}"
            )},
        ]
        async for ev in _stream_response(client, merge_messages, max_out):
            yield ev
    except Exception as e:
        yield _sse({'type': 'error', 'error': str(e)})