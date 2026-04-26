from anthropic import Anthropic
from dotenv import load_dotenv
import os
import subprocess

from utils import cprint, log, log_and_print

load_dotenv(override=True)
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SECTION = "s01"

tools = [{
    "name": "bash",
    "description": "执行bash命令",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"]
    }
}]

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
                cmd = block.input["command"]
                cprint("tool_cmd", cmd)
                log(SECTION, "tool_cmd", cmd)

                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True
                )
                output = (result.stdout + result.stderr).strip() or "(no output)"
                cprint("tool_out", output)
                log(SECTION, "tool_out", output)

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output
                })

        messages.append({"role": "user", "content": results})