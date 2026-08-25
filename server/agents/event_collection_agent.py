import json
from datetime import datetime


class EventCollectionAgent:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def run(self, user_message: str, preferences: dict) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = f"""你是事项收集 Agent，负责提取旅行和出差的基础信息。

当前日期：{today}
用户已保存偏好：{json.dumps(preferences, ensure_ascii=False)}
用户输入：{user_message}

请提取以下字段：
- origin：出发地
- destination：目的地
- start_date：出发日期，必须是 YYYY-MM-DD
- end_date：返程日期，必须是 YYYY-MM-DD
- duration_days：行程天数
- return_location：返程地
- trip_purpose：行程目的

相对日期请根据当前日期换算；缺失信息填 null，并放入 missing_info。
只返回合法 JSON：
{{"origin":null,"destination":null,"start_date":null,"end_date":null,"duration_days":null,"return_location":null,"trip_purpose":null,"missing_info":[],"extracted_count":0,"summary":""}}"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是行程信息提取专家，只输出合法JSON。"},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            timeout=30,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(content)
