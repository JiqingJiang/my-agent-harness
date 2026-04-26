# s02: Tool Use — 多工具 + Dispatch Map
#
# 在 s01 的基础上升级：从只有 bash 变成 4 个工具，循环本身一行没改。
#
# 核心概念：
#   - TOOL_HANDLERS 字典：{工具名: 处理函数}，一行查找替代 if/elif
#   - handler(**block.input)：函数参数名必须和 input_schema 的 key 一致
#   - 所有处理函数必须有 try/except，返回错误字符串而非崩溃
#
# 试试这些 prompt：
#   1. 读一下 requirements.txt 的内容          → 看 agent 选 read_file
#   2. 当前目录有什么                          → 看 agent 选 bash
#   3. 创建一个 hello.py，内容是 print("Hello")  → 看 agent 选 write_file
#   4. 读一下 hello.py                         → 验证写入
#   5. 把 hello.py 里的 Hello 改成 Agent       → 看 agent 选 edit_file
#   6. 读一下 requirement.txt                   → 故意打错文件名，看 agent 自动纠错

from anthropic import Anthropic
from dotenv import load_dotenv
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import cprint, log, log_and_print

load_dotenv(override=True)
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SECTION = "s02"

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
}]

def run_read(path: str, limit=None):
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"

def run_bash(command: str):
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True
    )
    output = (result.stdout + result.stderr).strip() or "(no output)"
    return output

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


TOOL_HANDLERS = {
    "bash":      run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
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
