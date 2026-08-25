import json
import os
import asyncio
import time
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel
from dotenv import load_dotenv
from server.agents import EventCollectionAgent, ItineraryPlanningAgent, MemoryQueryAgent, PreferenceAgent
from server.memory import JsonMemory
from server.skill_registry import get_skill_registry


load_dotenv(Path(__file__).resolve().parent / ".env")


app = FastAPI(title="Aligo Travel Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    user_id: str = "demo-user"
    session_id: str = "demo-session"


class IntentRequest(BaseModel):
    message: str


def build_context_message(message: str, recent_messages: list[dict]) -> str:
    """把短期记忆显式交给意图和业务 Agent，避免只存不使用。"""
    previous = [item for item in recent_messages if item.get("content") != message]
    if not previous:
        return message
    history = "\n".join(
        f"{item.get('role', 'user')}: {item.get('content', '')}" for item in previous[-10:]
    )
    return f"【近期对话上下文】\n{history}\n【当前用户输入】\n{message}"


def summarize_memory_background(user_id: str, session_id: str) -> None:
    """在响应返回后压缩近期对话，写入长期记忆。"""
    memory = JsonMemory(user_id)
    messages = memory.get_recent_messages(session_id, max_messages=20)
    if not messages:
        return
    try:
        client = get_client()
        response = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            messages=[
                {
                    "role": "system",
                    "content": "你是长期记忆整理模块。只保留稳定的用户偏好、常去地点、预算和出行习惯，忽略寒暄和一次性信息。用简洁中文输出，不要编造。",
                },
                {
                    "role": "user",
                    "content": (
                        f"已有长期摘要：{memory.get_summary() or '暂无'}\n"
                        f"近期对话：{json.dumps(messages, ensure_ascii=False)}\n"
                        "请更新长期记忆摘要。"
                    ),
                },
            ],
            stream=False,
            timeout=30,
        )
        summary = (response.choices[0].message.content or "").strip()
        if summary:
            memory.save_summary(summary)
    except Exception:
        # 后台总结失败不影响用户已经拿到的主回答。
        return


def get_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")}


@app.get("/api/skills")
def skills_status() -> dict:
    """查看已发现的 Skill 元数据和已经懒加载的插件。"""
    registry = get_skill_registry()
    return {"skills": registry.metadata(), "loaded": registry.loaded()}


@app.get("/api/memory/{user_id}")
def memory_status(user_id: str, session_id: str = "demo-session") -> dict:
    """用于学习和调试：查看两层记忆及 Redis 是否连接。"""
    return JsonMemory(user_id).status(session_id)


@app.post("/api/intent")
def classify_intent(request: IntentRequest, preferences: Optional[dict] = None) -> dict:
    if preferences is None:
        try:
            from server.agentscope_workflow import run_intent_workflow
            return run_intent_workflow(request.message, {})
        except ImportError:
            pass
    client = get_client()
    preference_context = json.dumps(preferences or {}, ensure_ascii=False)
    prompt = f"""你是差旅助手的意图识别模块。
请根据语义判断用户输入属于哪一类，只返回JSON，不要输出其他内容。

可选意图：
- trip_planning：规划行程
- policy_query：查询差旅政策
- real_time_query：查询天气、航班、酒店、火车、高铁、路线、价格或房态等实时信息
- preference_update：记录或修改出行偏好
- memory_query：查询已保存的偏好或历史
- general_chat：普通聊天

输出格式：{{"intent":"意图名称","reason":"简短原因"}}

判断规则：
- 用户询问“我的”“我之前”“我保存的”“我去过什么地方”等个人历史或偏好时，必须选择 memory_query。
- 用户表达新增或修改偏好时，选择 preference_update。
- 只问某个城市有什么酒店、航班、车次、天气或实时价格时，选择 real_time_query，不要选择 trip_planning。
- 明确表达“想去/准备去/要去”某地并带有未来时间时，也可以选择 trip_planning；只有单纯查询酒店、航班、车次、天气或价格时才选择 real_time_query。
- 如果当前输入是对上一轮的补充（如“杭州出发的”“住两晚”），结合近期对话上下文继承上一轮意图，不要单独按短句分类。
- 普通寒暄或与差旅无关的问题，才选择 general_chat。

当前用户已保存的偏好：{preference_context}

用户输入：{request.message}"""
    response = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        messages=[
            {"role": "system", "content": "你是一个意图识别专家，只输出合法JSON。"},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(content)


async def route_intent_async(intent: dict, message: str, client: OpenAI, user_id: str) -> Optional[dict]:
    """优先级 + 同组并行的混合调度器。

    偏好更新先执行，因为后续行程规划可能依赖最新偏好；其余互不依赖
    的查询放在同一阶段，通过 to_thread 并发运行现有同步 Agent 包装器。
    """
    intent_types = [item.get("type") for item in intent.get("intents", [])]
    if not intent_types and intent.get("intent"):
        intent_types = [intent["intent"]]
    results = {}
    phases = []
    registry = get_skill_registry()

    async def run_phase(name: str, tasks: dict[str, object]) -> None:
        if not tasks:
            return
        started = time.perf_counter()
        values = await asyncio.gather(
            *(asyncio.to_thread(task) for task in tasks.values()),
            return_exceptions=True,
        )
        phase_results = {}
        for key, value in zip(tasks, values):
            if isinstance(value, Exception):
                phase_results[key] = {"error": str(value)}
            else:
                phase_results[key] = value
        results.update(phase_results)
        phases.append({
            "name": name,
            "parallel_tasks": list(tasks),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        })

    # Phase 1：偏好必须先落盘，后续任务才能读取最新偏好。
    if "preference_update" in intent_types:
        def preference_task():
            return registry.run_for_intent(
                "preference_update", message=message, user_id=user_id, client=client
            )

        started = time.perf_counter()
        result = await asyncio.to_thread(preference_task)
        if result.get("has_preferences"):
            memory = JsonMemory(user_id)
            result["current_preferences"] = memory.apply_preferences(result.get("preferences", []))
            result["saved"] = True
        results["preference"] = result
        phases.append({
            "name": "priority_1_preference",
            "parallel_tasks": ["preference"],
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        })

    # Phase 2：这些任务只读或各自查询外部数据，可以并行。
    parallel_tasks = {}
    if "memory_query" in intent_types:
        def memory_task():
            return registry.run_for_intent(
                "memory_query", message=message, user_id=user_id, client=client
            )
        parallel_tasks["memory"] = memory_task
    if "policy_query" in intent_types:
        parallel_tasks["policy"] = lambda: registry.run_for_intent(
            "policy_query", message=message, user_id=user_id, client=client
        )
    if "real_time_query" in intent_types:
        parallel_tasks["realtime"] = lambda: registry.run_for_intent(
            "real_time_query", message=message, user_id=user_id, client=client
        )
    if "trip_planning" in intent_types:
        def trip_task():
            return registry.run_for_intent(
                "trip_planning", message=message, user_id=user_id, client=client
            )
        parallel_tasks["trip"] = trip_task
    await run_phase("priority_2_parallel", parallel_tasks)
    if not results:
        return None
    results["_orchestration"] = {
        "mode": "priority_plus_parallel",
        "phases": phases,
    }
    return results


def route_intent(intent: dict, message: str, client: OpenAI, user_id: str) -> Optional[dict]:
    """兼容旧调用方的同步入口。"""
    return asyncio.run(route_intent_async(intent, message, client, user_id))


@app.post("/api/chat")
def chat(request: ChatRequest, background_tasks: BackgroundTasks) -> dict:
    client = get_client()
    memory = JsonMemory(request.user_id)
    recent_before = memory.get_recent_messages(request.session_id)
    memory.add_message(request.session_id, "user", request.message)
    context_message = build_context_message(request.message, recent_before)
    current_preferences = memory.get_preferences()
    try:
        from server.agentscope_workflow import run_intent_workflow
        intent = run_intent_workflow(context_message, current_preferences)
    except ImportError:
        intent = classify_intent(IntentRequest(message=context_message), current_preferences)
    skill_result = asyncio.run(route_intent_async(intent, context_message, client, request.user_id))
    current_preferences = JsonMemory(request.user_id).get_preferences()
    preference_context = json.dumps(current_preferences, ensure_ascii=False)
    skill_context = json.dumps(skill_result or {}, ensure_ascii=False)
    skill_keys = [key for key in (skill_result or {}) if not key.startswith("_")]
    if skill_result and "memory" in skill_result and skill_keys == ["memory"]:
        answer = skill_result["memory"]["answer"]
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    elif skill_result and "policy" in skill_result and skill_keys == ["policy"]:
        answer = skill_result["policy"]["answer"]
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    else:
        response = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            messages=[
                {
                    "role": "system",
                    "content": (
                       "你是一名专业的企业差旅规划助手，名字叫水精灵。"
    "你的任务是帮助用户规划出差行程、整理差旅政策，并管理用户的出行偏好。"
    "如果用户要规划行程，先确认出发地、目的地、出行时间、预算和偏好。"
    "如果信息不足，主动提问，不要直接猜测完整行程。"
    "涉及实时天气、交通、政策和价格时，如果没有可靠数据，必须明确说明，不能编造。"
    "回答要简洁、专业，并优先使用分点结构。"
f"当前用户已保存的偏好是：{preference_context}。回答时可以参考这些偏好，但不要声称完成了不存在的查询。"
f"后端技能执行结果是：{skill_context}。如果其中包含行程规划结果，请基于它回答用户。"
                    ),
                },
                {"role": "user", "content": context_message},
            ],
            stream=False,
            timeout=30,
        )
        answer = response.choices[0].message.content
        model = response.model
    memory.add_message(request.session_id, "assistant", answer)
    background_tasks.add_task(summarize_memory_background, request.user_id, request.session_id)
    return {
        "answer": answer,
        "model": model,
        "user_id": request.user_id,
        "session_id": request.session_id,
        "intent": intent,
        "skill_result": skill_result,
        "memory": {
            "short_term_messages": len(memory.get_recent_messages(request.session_id)),
            "redis_connected": bool(memory.redis),
            "summary": memory.get_summary(),
        },
    }
