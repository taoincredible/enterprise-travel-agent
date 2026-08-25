def run(message: str, user_id: str = "demo-user", client=None):
    from server.agentscope_workflow import run_rag_workflow
    return run_rag_workflow(message)
