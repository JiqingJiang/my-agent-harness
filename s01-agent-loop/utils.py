import os
import sys
from datetime import datetime


# ── 配置 ──────────────────────────────────────────────────────────────

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")


# ── ANSI 颜色 ─────────────────────────────────────────────────────────

class Color:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"

    # 角色
    USER       = "\033[36m"   # 青色
    ASSISTANT  = "\033[32m"   # 绿色
    TOOL_CMD   = "\033[33m"   # 黄色
    TOOL_OUT   = "\033[90m"   # 灰色
    SYSTEM     = "\033[35m"   # 紫色
    ERROR      = "\033[31m"   # 红色

    @staticmethod
    def wrap(text: str, color: str) -> str:
        return f"{color}{text}{Color.RESET}"


# ── 彩色终端打印 ──────────────────────────────────────────────────────

def cprint(role: str, content: str):
    """
    彩色打印到终端。

    role: "user" | "assistant" | "tool_cmd" | "tool_out" | "system" | "error"
    """
    color_map = {
        "user":      (Color.USER,      "你"),
        "assistant": (Color.ASSISTANT, "Agent"),
        "tool_cmd":  (Color.TOOL_CMD,  "$"),
        "tool_out":  (Color.TOOL_OUT,  ""),
        "system":    (Color.SYSTEM,    "SYS"),
        "error":     (Color.ERROR,     "ERR"),
    }

    if role not in color_map:
        cprint("error", f"[cprint] 未知角色: {role}")
        return

    color, prefix = color_map[role]

    if role == "tool_out":
        # 工具输出：缩进显示，限制长度
        lines = content.split("\n")
        for line in lines[:20]:           # 最多 20 行
            print(f"  {Color.wrap(line[:120], color)}")
        if len(lines) > 20:
            print(f"  {Color.wrap(f'... 省略 {len(lines) - 20} 行', color)}")
    elif role == "user":
        print(f"\n{Color.wrap(prefix, color)}: {content}")
    elif role == "assistant":
        print(f"{Color.wrap(prefix, color)}: {content}")
    elif role == "tool_cmd":
        print(f"{Color.wrap(f'{prefix} {content}', color)}")
    else:
        print(f"{Color.wrap(f'[{prefix}] {content}', color)}")

    sys.stdout.flush()


# ── 文件日志 ──────────────────────────────────────────────────────────

def log(section: str, role: str, content: str):
    """
    写日志到文件。

    section: 小节名，如 "s01"
    role:    "user" | "assistant" | "tool_cmd" | "tool_out" | "system"
    content: 日志内容
    """
    section_dir = os.path.join(LOG_DIR, section)
    os.makedirs(section_dir, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(section_dir, f"{today}.log")

    timestamp = datetime.now().strftime("%H:%M:%S")

    # content 可能有多行，缩进处理
    lines = content.split("\n")
    formatted = f"[{timestamp}] [{role}] {lines[0]}\n"
    for line in lines[1:]:
        formatted += f"  {line}\n"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(formatted)


# ── 便捷函数：同时打印 + 记录 ────────────────────────────────────────

def log_and_print(section: str, role: str, content: str):
    """终端彩色打印 + 文件日志，一步到位。"""
    cprint(role, content)
    log(section, role, content)