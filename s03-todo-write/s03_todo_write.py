# s03: Todo Write — 让 Agent 先列计划再动手
#
# 新增概念：
#   - Todo 工具：外化 LLM 的计划，让进度可见、可追踪
#   - 全量替换模式：每次调用传入完整列表，不是追加
#   - System Prompt：用 system 参数引导 LLM 行为
#   - 三个状态：pending → in_progress → completed
#
# 试试这些 prompt：
#   1. 创建一个计算器项目，包含加减乘除功能    → 先列计划再执行
#   2. 做一个五子棋游戏                       → 观察是否先调用 todo
#   3. 帮我重构 utils.py                      → 观察任务状态变化

from anthropic import Anthropic
from dotenv import load_dotenv
import os
import subprocess

from utils import cprint, log, log_and_print

load_dotenv(override=True)
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SECTION = "s03"

SYSTEM_PROMPT = """
  - 面对多步任务时，先用 todo 工具列出计划
  - 开始执行某一步前，把它标记为 in_progress
  - 完成后标记为 completed
  - 列完计划后立即开始执行，不要等待用户确认。"""

tools = [{
    "name": "bash",
    "description": "执行bash命令",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "读文件",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "创建文件，写入内容",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "读取文件，找到 old_text，替换成 new_text，写回",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
            "required": ["path", "old_text", "new_text"]
        }
    },
    {
        "name": "todo",
        "description": "更新任务列表。传入完整的 items 数组，每次全量替换。",
        "input_schema": {
            "type": "object",
            "properties": {"items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string"}
                    },
                    "required": ["content", "status"]
                }
            }},
            "required": ["items"]
        }
    }
]

todolist = []

def run_read(path: str, limit=None):
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"

def run_bash(command: str):
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", "sleep "]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )
        output = (result.stdout + result.stderr).strip() or "(no output)"
        return output
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_write(path: str, content: str):
    try:
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"Wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str):
    try:
        content = open(path).read()
        if old_text not in content:
            return f"Error: '{old_text}' not found in {path}"
        new_content = content.replace(old_text, new_text, 1)
        open(path, "w").write(new_content)
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

def run_todo(items):
    todolist.clear()
    todolist.extend(items)
    return f"Todo updated ({len(todolist)} items): " + str(todolist)

TOOL_HANDLERS = {
    "bash":      run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "todo":      run_todo,
}

messages = []

while True:
    try:
        query = input("\033[36m你: \033[0m")
    except (EOFError, KeyboardInterrupt):
        print()
        break

    if not query.strip() or query.strip().lower() in ("q", "exit"):
        log_and_print(SECTION, "system", "会话结束")
        break

    messages.append({"role": "user", "content": query})
    log(SECTION, "user", query)

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            for block in response.content:
                if hasattr(block, "text"):
                    cprint("assistant", block.text)
                    log(SECTION, "assistant", block.text)
            break

        results = []
        for block in response.content:
            if block.type == "tool_use":
                cprint("tool_cmd", block.name)
                log(SECTION, "tool_cmd", block.name)

                handler = TOOL_HANDLERS[block.name]
                output = handler(**block.input)

                cprint("tool_out", output)
                log(SECTION, "tool_out", output)

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output
                })

        messages.append({"role": "user", "content": results})