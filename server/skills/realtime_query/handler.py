def run(message: str, user_id: str = "demo-user", client=None):
    from server.agentscope_workflow import run_realtime_workflow
    return run_realtime_workflow(message)
