# s05: Skill Loading — 按需加载知识
#
# 新增概念：
#   - SkillLoader：扫描 skills/ 目录，解析 SKILL.md 的 frontmatter 和 body
#   - 两层注入：system prompt 只放目录（Layer 1），load_skill 工具返回完整知识（Layer 2）
#   - 工具 description 写法：做什么 + 什么时候用 + 跟其他工具的区别
#   - f-string system prompt：SKILL_LOADER 必须在 SYSTEM_PROMPT 之前创建
#
# 试试这些 prompt：
#   1. 加载 code-review 这个 skill                    → 观察 load_skill 工具调用
#   2. 帮我审查一下 utils.py 的代码                   → LLM 先加载 skill 再审查
#   3. 我想处理一个 PDF 文件，该怎么做                 → LLM 先加载 pdf skill

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import Anthropic
from dotenv import load_dotenv
import os
import subprocess

from utils import cprint, log, log_and_print
from SkillLoader import SkillLoader

load_dotenv(override=True)
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
SKILL_LOADER = SkillLoader("skills")

SECTION = "s05"

SYSTEM_PROMPT = f"""
  - 面对多步任务时，**必须**先用 todo 工具列出计划
  - 开始执行某一步前，把它标记为 in_progress
  - 完成后标记为 completed
  - 列完计划后立即开始执行，不要等待用户确认
  - 可以使用 task 工具派生子 agent 执行具体子任务
  - 可以使用 load_skill 工具加载专业知识
  Skills available:
{SKILL_LOADER.get_descriptions()}
"""

SUBAGENT_SYSTEM_PROMPT = "你是一个子 agent。执行给定的任务，完成后返回一段简洁的摘要。"

# ── 工具定义 ──

base_tools = [
    {
        "name": "bash",
        "description": "执行 bash 命令。用于运行脚本、安装依赖、查看目录结构等系统操作。",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "读取文件内容。查看已有代码、配置文件或日志时使用。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "创建新文件并写入内容。需要创建新代码文件或配置文件时使用。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "精确替换文件中的文本片段。修改现有代码或配置时使用，比全量重写更安全。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
            "required": ["path", "old_text", "new_text"]
        }
    }
]

todo_tool = {
    "name": "todo",
    "description": "管理任务计划。多步任务开始前先用此工具列出所有步骤，执行中更新状态（pending → in_progress → completed）。传入完整的 items 数组，每次全量替换。",
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

task_tool = {
    "name": "task",
    "description": "派生子 agent 执行独立的子任务。子 agent 拥有干净的上下文，适合需要大量探索或多文件操作的任务，完成后只返回摘要。",
    "input_schema": {
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
        "required": ["prompt"]
    }
}

load_skill = {
    "name": "load_skill",
    "description": "按需加载专业知识。面对不熟悉的领域（如代码审查、PDF处理、MCP构建等）时，先加载对应 skill 获取专家级指引。",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"]
    }
}

# 主 agent 拥有全部工具（base + todo + task + load_skill）
parent_tools = base_tools + [todo_tool, task_tool, load_skill]
# 子 agent 拥有基础工具 + load_skill（不能列计划、不能再派生，但可以加载知识）
child_tools = base_tools + [load_skill]

# ── Handler 函数 ──

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

def run_task(prompt: str) -> str:
    """派生子 agent 执行任务，返回摘要。"""
    cprint("tool_cmd", f"[subagent] {prompt[:60]}...")
    result = run_subagent(prompt)
    cprint("tool_out", f"[subagent result] {result[:200]}...")
    return result

def run_subagent(prompt: str) -> str:
    """子 agent：独立上下文，最多 30 轮，返回文本摘要。"""
    sub_messages = [{"role": "user", "content": prompt}]

    for _ in range(30):  # 安全限制：最多 30 轮
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=SUBAGENT_SYSTEM_PROMPT,
            tools=child_tools,
            messages=sub_messages
        )

        sub_messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = BASE_HANDLERS[block.name]
                output = handler(**block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)[:50000]  # 截断防止上下文爆炸
                })

        sub_messages.append({"role": "user", "content": results})

    # 提取最终文本摘要
    text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    return text or "(no summary)"

def run_load_skill(name: str) -> str:
    return SKILL_LOADER.get_content(name)

# ── Dispatch Map ──

# 基础工具的 handler（主 agent 和子 agent 共用）
BASE_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "load_skill": run_load_skill
}

# 主 agent 的 handler（基础 + todo + task）
PARENT_HANDLERS = {
    **BASE_HANDLERS,
    "todo": run_todo,
    "task": run_task,
}

# ── 主循环 ──

todolist = []
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
            tools=parent_tools,
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

                handler = PARENT_HANDLERS[block.name]
                output = handler(**block.input)

                cprint("tool_out", output)
                log(SECTION, "tool_out", output)

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output
                })

        messages.append({"role": "user", "content": results})
