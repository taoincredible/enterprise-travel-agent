def run(message: str, user_id: str, client=None):
    try:
        from server.agentscope_workflow import run_memory_query_workflow
        return run_memory_query_workflow(message, user_id)
    except ImportError:
        from server.agents.memory_query_agent import MemoryQueryAgent
        return MemoryQueryAgent(client=client, model="deepseek-v4-flash").run(user_id)
