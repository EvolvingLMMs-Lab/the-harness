"""One bounded task, its context, budget and child executions."""

def __getattr__(name):
    if name == "TaskRun":
        from .run import TaskRun
        return TaskRun
    raise AttributeError(name)
