import asyncio
import json
import os
import re
from datetime import date, timedelta
from typing import Any

import agentscope
from agentscope.agent import AgentBase
from agentscope.message import Msg
from agentscope.model import OpenAIChatModel
from server.memory import JsonMemory
from server.skill_registry import get_skill_registry
from pymilvus import MilvusClient
from sentence_transformers import SentenceTransformer
from pathlib import Path


_RAG_MODEL = None
_RAG_CLIENT = None


def _content(response: Any) -> str:
    value = response.content if hasattr(response, "content") else response
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif hasattr(item, "text"):
                texts.append(item.text)
        return "".join(texts)
    return str(value)


class EventCollectionASAgent(AgentBase):
    def __init__(self, model):
        super().__init__()
        self.name = "EventCollectionAgent"
        self.model = model

    async def reply(self, x):
        data = json.loads(x.content)
        message = data["message"]
        today = data["today"]
        prompt = f"""你是事项收集 Agent。当前日期是 {today}。
从用户输入中提取 origin、destination、start_date、end_date、duration_days、return_location、trip_purpose。
日期必须是 YYYY-MM-DD；缺失字段填 null，并列入 missing_info。只返回合法 JSON。
用户输入：{message}
输出格式：{{"origin":null,"destination":null,"start_date":null,"end_date":null,"duration_days":null,"return_location":null,"trip_purpose":null,"missing_info":[],"extracted_count":0,"summary":""}}"""
        response = await self.model([
            {"role": "system", "content": "只输出合法JSON。"},
            {"role": "user", "content": prompt},
        ])
        return Msg(name=self.name, content=_content(response), role="assistant")


class IntentionASAgent(AgentBase):
    def __init__(self, model):
        super().__init__()
        self.name = "IntentionAgent"
        self.model = model

    async def reply(self, x):
        data = json.loads(x.content)
        prompt = f"""你是差旅助手的意图识别 Agent。
根据语义判断用户输入包含哪些意图，只返回合法 JSON。一个输入可以包含多个意图。

当前可用 Skill 元数据（只用于路由判断，执行阶段才加载具体 Skill）：
{get_skill_registry().metadata_prompt()}

可选意图：
- trip_planning：规划行程
- policy_query：查询差旅政策
- real_time_query：查询天气、航班、酒店、火车、高铁、路线、价格或房态等实时信息
- preference_update：记录或修改出行偏好
- memory_query：查询已保存的偏好或历史
- general_chat：普通聊天

规则：询问“我的”“我之前”“我保存的”时选择 memory_query；表达新增或修改偏好时选择 preference_update。
明确表达“想去/准备去/要去”某地并带有未来时间时，也视为 trip_planning；只有单纯查询酒店、航班、车次、天气或价格时才选择 real_time_query。
只问某个城市有什么酒店、航班、车次、天气或实时价格时，选择 real_time_query，不要选择 trip_planning。
例如：“郑州有什么酒店”→ real_time_query；“帮我规划郑州三天出差”→ trip_planning。
如果当前输入是“杭州出发的”“那预算呢”“住两晚”等不完整补充，必须结合【近期对话上下文】继承上一轮的业务意图，不要把补充信息误判成新的偏好或普通聊天。
规划行程和表达偏好可以同时存在；实时查询和行程规划只有在用户明确同时提出两件事时才同时返回。
当前用户偏好：{json.dumps(data['preferences'], ensure_ascii=False)}
用户输入：{data['message']}
输出格式：{{"intents":[{{"type":"意图名称","confidence":0.95,"reason":"简短原因"}}]}}"""
        response = await self.model([
            {"role": "system", "content": "你是意图识别专家，只输出合法JSON。"},
            {"role": "user", "content": prompt},
        ])
        return Msg(name=self.name, content=_content(response), role="assistant")


class PreferenceASAgent(AgentBase):
    def __init__(self, model):
        super().__init__()
        self.name = "PreferenceAgent"
        self.model = model

    async def reply(self, x):
        data = json.loads(x.content)
        prompt = f"""你是用户偏好分析 Agent。
从用户输入中提取长期出行偏好，只返回合法 JSON。
“还”“也”“另外”使用 append；“改成”“换成”“搬家到”使用 replace；首次提及使用 replace。
已有偏好：{json.dumps(data['preferences'], ensure_ascii=False)}
用户输入：{data['message']}
输出格式：{{"preferences":[{{"type":"偏好类型","value":"偏好值","action":"append或replace"}}],"has_preferences":true或false}}"""
        response = await self.model([
            {"role": "system", "content": "你是偏好提取专家，只输出合法JSON。"},
            {"role": "user", "content": prompt},
        ])
        return Msg(name=self.name, content=_content(response), role="assistant")


class MemoryQueryASAgent(AgentBase):
    def __init__(self, model):
        super().__init__()
        self.name = "MemoryQueryAgent"
        self.model = model

    async def reply(self, x):
        data = json.loads(x.content)
        prompt = f"请基于以下真实用户偏好，简洁回答用户问题，不要编造：\n用户偏好：{json.dumps(data['preferences'], ensure_ascii=False)}\n用户问题：{data['message']}"
        response = await self.model([
            {"role": "system", "content": "你是用户记忆查询 Agent。"},
            {"role": "user", "content": prompt},
        ])
        return Msg(
            name=self.name,
            content=json.dumps({"answer": _content(response), "preferences": data["preferences"]}, ensure_ascii=False),
            role="assistant",
        )


class RAGKnowledgeASAgent(AgentBase):
    def __init__(self, model):
        super().__init__()
        self.name = "RAGKnowledgeAgent"
        self.model = model

    async def reply(self, x):
        data = json.loads(x.content)
        root = Path(__file__).resolve().parent.parent
        global _RAG_MODEL, _RAG_CLIENT
        if _RAG_MODEL is None:
            _RAG_MODEL = SentenceTransformer(str(root / "data/models/bge-small-zh-v1.5"))
        if _RAG_CLIENT is None:
            _RAG_CLIENT = MilvusClient(str(root / "data/rag_knowledge/milvus_lite.db"))
        _RAG_CLIENT.load_collection(collection_name="business_travel_knowledge")
        query_vector = _RAG_MODEL.encode(data["message"]).tolist()
        hits = _RAG_CLIENT.search(
            collection_name="business_travel_knowledge",
            data=[query_vector],
            limit=3,
            output_fields=["content", "metadata"],
        )
        sources = []
        for hit in hits[0]:
            entity = hit.get("entity", {})
            sources.append({"content": entity.get("content", ""), "metadata": entity.get("metadata", "")})
        context = "\n\n".join(item["content"] for item in sources)
        prompt = f"""你是企业差旅政策问答 Agent。
请严格根据参考资料回答，不要编造资料中没有的政策、金额或条件。
如果资料不足，请明确说无法从知识库确认。

参考资料：
{context}

用户问题：{data['message']}
请给出简洁、准确的回答，并说明参考来源文件。"""
        response = await self.model([
            {"role": "system", "content": "你是严格基于资料回答的 RAG 问答助手。"},
            {"role": "user", "content": prompt},
        ])
        return Msg(
            name=self.name,
            content=json.dumps({"answer": _content(response), "sources": sources}, ensure_ascii=False),
            role="assistant",
        )


class RealTimeQueryASAgent(AgentBase):
    """第一版实时查询 Agent：根据问题类型调用 MCP Tool。"""

    def __init__(self, model):
        super().__init__()
        self.name = "RealTimeQueryAgent"
        self.model = model

    async def reply(self, x):
        import os
        from server.mcp_client import call_mcp_tool_async, call_trvl_async

        data = json.loads(x.content)
        message = data["message"]
        if self._is_weather_query(message):
            city = self._extract_city(message)
            if not city:
                return Msg(
                    name=self.name,
                    content=json.dumps({"success": False, "tool": "get_weather", "error": "未识别到城市"}, ensure_ascii=False),
                    role="assistant",
                )
            result = await call_mcp_tool_async("get_weather", {"city": city})
            result["mcp_server"] = "travel-tools"
            result.setdefault("data_source", result.get("source", "wttr.in"))
            result["tool"] = "get_weather"
            return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

        trvl_intent = self._trvl_intent(message)
        if os.getenv("ENABLE_TRVL_MCP", "false").lower() == "true" and trvl_intent:
            extractor = TravelQueryParamASAgent(self.model)
            extracted_msg = await extractor(
                Msg(
                    name="RealTimeQueryAgent",
                    content=json.dumps(
                        {"message": message, "intent": trvl_intent, "today": date.today().isoformat()},
                        ensure_ascii=False,
                    ),
                    role="user",
                )
            )
            extracted = json.loads(_content(extracted_msg))
            params = self._normalize_trvl_params(trvl_intent, extracted.get("params", {}))
            params = self._complete_trvl_params(trvl_intent, params, message)
            missing_params = self._required_missing(trvl_intent, params)
            if missing_params:
                extracted["tool"] = "travel"
                extracted["intent"] = trvl_intent
                extracted["success"] = False
                extracted["params"] = params
                extracted["missing_params"] = missing_params
                return Msg(name=self.name, content=json.dumps(extracted, ensure_ascii=False), role="assistant")
            result = await call_trvl_async(trvl_intent, params, query=message)
            result["tool"] = "travel"
            result["intent"] = trvl_intent
            result.setdefault("data_source", "trvl 聚合旅行数据源")
            result["extracted_params"] = params
            return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

        result = await call_mcp_tool_async("search_web", {"query": message, "max_results": 5})
        result["mcp_server"] = "travel-tools"
        result.setdefault("data_source", "DDGS 公开网页搜索")
        result["tool"] = "search_web"
        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

    @staticmethod
    def _is_weather_query(message: str) -> bool:
        return any(word in message for word in ("天气", "气温", "下雨", "降雨", "预报"))

    @staticmethod
    def _trvl_intent(message: str) -> str:
        if any(word in message for word in ("航班", "机票", "飞机", "飞行")):
            return "flights"
        if any(word in message for word in ("酒店", "住宿", "房间")):
            return "hotels"
        if any(word in message for word in ("高铁", "火车", "车次", "铁路")):
            return "ground"
        return ""

    @staticmethod
    def _extract_city(message: str) -> str:
        cities = (
            "北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "苏州",
            "天津", "重庆", "厦门", "青岛", "大连", "宁波", "长沙", "郑州", "济南", "昆明",
        )
        return next((city for city in cities if city in message), "")

    @staticmethod
    def _normalize_trvl_params(intent: str, params: dict) -> dict:
        if intent == "flights":
            normalized = {
                "origin": RealTimeQueryASAgent._airport_code(params.get("from")),
                "destination": RealTimeQueryASAgent._airport_code(params.get("to")),
                "departure_date": params.get("date"),
            }
            if params.get("max_price") is not None:
                normalized["max_price"] = params["max_price"]
            return normalized
        if intent == "hotels":
            normalized = {
                "location": params.get("location") or params.get("city"),
                "check_in": params.get("check_in") or params.get("checkin"),
                "check_out": params.get("check_out") or params.get("checkout"),
            }
            if params.get("max_price") is not None:
                normalized["max_price"] = params["max_price"]
            return normalized
        return params

    @staticmethod
    def _required_missing(intent: str, params: dict) -> list[str]:
        required = {
            "flights": ("origin", "destination", "departure_date"),
            "hotels": ("location", "check_in", "check_out"),
            "ground": ("from", "to", "date"),
        }.get(intent, ())
        return [key for key in required if not params.get(key)]

    @staticmethod
    def _complete_trvl_params(intent: str, params: dict, message: str) -> dict:
        """补全可以从用户原话确定的地点、相对日期和住宿时长。"""
        if intent != "hotels":
            return params

        completed = dict(params)
        if not completed.get("location"):
            station = re.search(r"([\u4e00-\u9fa5]{2,8}(?:东站|西站|南站|北站|车站))", message)
            if station:
                completed["location"] = station.group(1)
            else:
                cities = ("北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "郑州", "苏州")
                completed["location"] = next((city for city in cities if city in message), None)

        if not completed.get("check_in"):
            offset = 1 if "明天" in message else 2 if "后天" in message else None
            if offset is not None:
                completed["check_in"] = (date.today() + timedelta(days=offset)).isoformat()

        if not completed.get("check_out") and completed.get("check_in"):
            stay = re.search(r"(?:住|住上)\s*(\d+)\s*(?:天|晚)", message)
            chinese_numbers = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
            if not stay:
                stay_cn = re.search(r"(?:住|住上)\s*([一两二三四五六七])\s*(?:天|晚)", message)
                nights = chinese_numbers.get(stay_cn.group(1)) if stay_cn else None
            else:
                nights = int(stay.group(1))
            if nights:
                completed["check_out"] = (date.fromisoformat(completed["check_in"]) + timedelta(days=nights)).isoformat()
        return completed

    @staticmethod
    def _airport_code(value) -> str:
        codes = {
            "杭州": "HGH", "郑州": "CGO", "上海": "SHA,PVG", "北京": "PEK,PKX",
            "广州": "CAN", "深圳": "SZX", "成都": "CTU,TFU", "西安": "XIY",
            "南京": "NKG", "厦门": "XMN", "武汉": "WUH", "重庆": "CKG",
        }
        value = str(value or "").strip()
        return codes.get(value, value)


class TravelQueryParamASAgent(AgentBase):
    """把自然语言旅行查询转换成 trvl 所需的结构化参数。"""

    def __init__(self, model):
        super().__init__()
        self.name = "TravelQueryParamAgent"
        self.model = model

    async def reply(self, x):
        data = json.loads(x.content)
        prompt = f"""你是旅行查询参数提取 Agent。当前日期是 {data['today']}。
根据用户问题和查询类型，提取调用外部旅行工具所需的参数，只返回合法 JSON。

查询类型：{data['intent']}
用户问题：{data['message']}

参数规则：
- flights 或 ground：提取 from、to、date；航班还要提取预算 max_price（如果用户提供）；
- hotels：提取 city、checkin、checkout；“明天住两天”可以推导入住和退房日期；传给工具时映射为 location、check_in、check_out；
- 相对日期如“明天”“下周一”必须换算成 YYYY-MM-DD；
- 无法确定的字段填 null，并放入 missing_params；
- 不要猜测用户没有提供的城市、日期或价格。

输出格式：
{{"params":{{}},"missing_params":[],"summary":""}}
"""
        response = await self.model([
            {"role": "system", "content": "你是结构化参数提取专家，只输出合法JSON。"},
            {"role": "user", "content": prompt},
        ])
        return Msg(name=self.name, content=_content(response), role="assistant")


class ItineraryPlanningASAgent(AgentBase):
    def __init__(self, model):
        super().__init__()
        self.name = "ItineraryPlanningAgent"
        self.model = model

    async def reply(self, x):
        data = json.loads(x.content)
        prompt = f"""你是行程规划 Agent。
根据用户需求、已提取的行程信息和用户偏好生成每日出差行程。
不要编造实时车次、票价、天气或酒店空房。只返回合法 JSON。
用户需求：{data['message']}
行程信息：{json.dumps(data['event'], ensure_ascii=False)}
用户偏好：{json.dumps(data['preferences'], ensure_ascii=False)}
输出格式：{{"itinerary":{{"title":"","duration":"","route":"","daily_plans":[],"notes":[],"estimated_budget":""}},"planning_complete":true,"missing_info":[]}}"""
        response = await self.model([
            {"role": "system", "content": "只输出合法JSON。"},
            {"role": "user", "content": prompt},
        ])
        return Msg(name=self.name, content=_content(response), role="assistant")


class TravelOrchestrationAgent(AgentBase):
    def __init__(self, model):
        super().__init__()
        self.name = "TravelOrchestrationAgent"
        self.event_agent = EventCollectionASAgent(model)
        self.plan_agent = ItineraryPlanningASAgent(model)

    async def reply(self, x):
        data = json.loads(x.content)
        event_msg = await self.event_agent(
            Msg(name="Orchestrator", content=json.dumps(data, ensure_ascii=False), role="user")
        )
        event = json.loads(_content(event_msg))
        plan_msg = await self.plan_agent(
            Msg(
                name="Orchestrator",
                content=json.dumps({**data, "event": event}, ensure_ascii=False),
                role="user",
            )
        )
        return Msg(
            name=self.name,
            content=json.dumps({"event": event, "itinerary": json.loads(_content(plan_msg))}, ensure_ascii=False),
            role="assistant",
        )


def run_trip_workflow(message: str, preferences: dict) -> dict:
    async def run():
        model = _get_model()
        workflow = TravelOrchestrationAgent(model)
        result = await workflow(
            Msg(
                name="user",
                content=json.dumps(
                    {"message": message, "preferences": preferences, "today": __import__("datetime").date.today().isoformat()},
                    ensure_ascii=False,
                ),
                role="user",
            )
        )
        return json.loads(result.content)

    return asyncio.run(run())


def _get_model():
    if not getattr(_get_model, "initialized", False):
        agentscope.init(project="travel-assistant", name="travel-workflow", logging_level="WARNING")
        _get_model.initialized = True
    return OpenAIChatModel(
        model_name=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        stream=False,
        client_kwargs={"base_url": "https://api.deepseek.com", "timeout": 30},
    )


def run_intent_workflow(message: str, preferences: dict) -> dict:
    async def run():
        agent = IntentionASAgent(_get_model())
        result = await agent(
            Msg(
                name="user",
                content=json.dumps(
                    {"message": message, "preferences": preferences, "today": date.today().isoformat()},
                    ensure_ascii=False,
                ),
                role="user",
            )
        )
        return json.loads(_content(result))

    return asyncio.run(run())


def run_preference_workflow(message: str, preferences: dict) -> dict:
    async def run():
        agent = PreferenceASAgent(_get_model())
        result = await agent(
            Msg(
                name="user",
                content=json.dumps({"message": message, "preferences": preferences}, ensure_ascii=False),
                role="user",
            )
        )
        return json.loads(_content(result))

    return asyncio.run(run())


def run_memory_query_workflow(message: str, user_id: str) -> dict:
    async def run():
        agent = MemoryQueryASAgent(_get_model())
        preferences = JsonMemory(user_id).get_preferences()
        result = await agent(
            Msg(
                name="user",
                content=json.dumps({"message": message, "preferences": preferences}, ensure_ascii=False),
                role="user",
            )
        )
        return json.loads(_content(result))

    return asyncio.run(run())


def run_rag_workflow(message: str) -> dict:
    async def run():
        agent = RAGKnowledgeASAgent(_get_model())
        result = await agent(
            Msg(name="user", content=json.dumps({"message": message}, ensure_ascii=False), role="user")
        )
        return json.loads(_content(result))

    return asyncio.run(run())


def run_realtime_workflow(message: str) -> dict:
    async def run():
        agent = RealTimeQueryASAgent(_get_model())
        result = await agent(
            Msg(name="user", content=json.dumps({"message": message}, ensure_ascii=False), role="user")
        )
        return json.loads(_content(result))

    return asyncio.run(run())
