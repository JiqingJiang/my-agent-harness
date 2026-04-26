# s01: Agent Loop — 从零手搓一个能调工具的 Agent

> 来源：learn-claude-code 项目 s01，邪修模式从零手搓，非抄代码。

## 1. 为什么需要循环？

LLM 是无状态推理 — 它返回的 bash 命令只是一个字符串，返回后就停了。

三个问题：
- **没有执行者**：命令躺在字符串里，没人跑
- **没有反馈**：执行结果 LLM 看不到
- **没有持续**：LLM 一次只能输出一步，多步任务需要来回好几轮

**循环就是解决这三件事的：你的代码当执行者，把结果喂回去，反复调用直到完成。**

## 2. Anthropic SDK 基础

### 2.1 初始化 Client

```python
from anthropic import Anthropic
from dotenv import load_dotenv
import os

load_dotenv(override=True)
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
```

- `base_url`：可以用 Anthropic 官方，也可以指向兼容 API（如 DeepSeek）
- `MODEL`：从环境变量读取模型名
- `.env` 文件配好 `ANTHROPIC_BASE_URL`、`MODEL_ID`、`ANTHROPIC_API_KEY` 即可

### 2.2 最简单的 API 调用

```python
message = client.messages.create(
    model=MODEL,
    max_tokens=8000,
    messages=[
        {"role": "user", "content": "你好"}
    ]
)
print(message.content[0].text)
```

就这么简单。发消息，拿回复。

## 3. Message 对象详解

`client.messages.create()` 返回的 Message 对象，核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | 这条消息的唯一 ID |
| `content` | list | **内容块列表**，里面有 TextBlock 或 ToolUseBlock |
| `model` | str | 实际使用的模型名 |
| `role` | str | 固定为 `"assistant"` |
| `stop_reason` | str | **关键！** 决定循环是否继续 |
| `type` | str | 固定为 `"message"` |
| `usage` | Usage | token 用量统计 |

### 3.1 content 列表中的两种块

**TextBlock** — LLM 的文字回复：
```python
TextBlock(
    text="这是回复的文字内容",
    type="text"
)
```

**ToolUseBlock** — LLM 想调用工具：
```python
ToolUseBlock(
    id="call_00_abc123",           # 工具调用的唯一 ID，后面 tool_result 要用它
    name="bash",                   # 工具名
    input={"command": "ls -la"},   # 工具参数
    type="tool_use"
)
```

**一次回复里可能同时有文字和工具调用**，所以 content 是列表不是单个值。

**取文字的正确方式：**
```python
for block in response.content:
    if hasattr(block, "text"):
        print(block.text)
```

### 3.2 stop_reason — 循环的开关

| 值 | 含义 | 循环怎么做 |
|----|------|-----------|
| `"tool_use"` | LLM 要用工具 | 执行工具，喂回结果，**继续循环** |
| `"end_turn"` | LLM 觉得回答完了 | **退出循环**，打印最终回复 |

**这是整个 agent loop 的核心退出条件。**

## 4. Messages 列表 — 对话历史的结构

Messages 是一个列表，每条消息是 `{"role": "...", "content": "..."}` 的字典。

### 4.1 Role 的种类

| role | 谁发的 | content 是什么 |
|------|--------|---------------|
| `"user"` | 用户（或你的代码模拟的用户） | 字符串，或 `[tool_result, ...]` |
| `"assistant"` | LLM | `response.content`（TextBlock/ToolUseBlock 列表） |

**注意：tool_result 在 API 协议里是 user 角色发的。** 这点反直觉但必须记住。

### 4.2 完整的多轮对话 messages 结构

```
messages = [
    {"role": "user",      "content": "帮我查看当前目录"},         # 第0条：原始问题
    {"role": "assistant", "content": [ToolUseBlock(...)]},       # 第1条：LLM 要用 bash
    {"role": "user",      "content": [tool_result_dict]},       # 第2条：你把执行结果喂回去
    {"role": "assistant", "content": [TextBlock(...)]},         # 第3条：LLM 给出最终回答
]
```

**关键：messages 是持续累积的，不是每次重建。** 循环里的每次 API 调用都看到完整历史。

## 5. Tools 定义 — 给 LLM 一双手

### 5.1 工具定义格式

```python
tools = [{
    "name": "bash",                    # 工具名（LLM 调用时引用这个名字）
    "description": "执行bash命令",      # 描述（LLM 根据描述判断什么时候用）
    "input_schema": {                   # 参数的 JSON Schema
        "type": "object",
        "properties": {
            "command": {"type": "string"}
        },
        "required": ["command"]
    }
}]
```

- **tools 在每次 API 调用时一起发送**，不是单独发送的
- LLM 同时看到消息和工具列表，自己决定用不用
- 加新工具只需要往 tools 列表里追加一个字典，循环完全不用动（s02 的核心思想）

### 5.2 description 很重要

description 写得好不好，直接决定 LLM 会不会正确使用工具。
- 太模糊：LLM 会在不该用的时候用
- 太具体：LLM 可能不理解工具的能力边界

## 6. Tool Result — 把执行结果喂回 LLM

### 6.1 tool_result 格式

```python
tool_result = {
    "type": "tool_result",              # 固定
    "tool_use_id": block.id,            # 对应 ToolUseBlock 的 id，不能错
    "content": "ls 的输出结果..."        # 执行命令拿到的字符串
}
```

### 6.2 tool_use_id 的作用

LLM 发出工具调用时生成一个唯一 ID，执行完你要把结果通过这个 ID 对应回去。

**为什么需要？** 因为 LLM 可能一次调用多个工具，需要用 ID 精确匹配"哪个结果对应哪个调用"。

```
LLM 输出: ToolUseBlock(id="aaa", command="ls")
           ToolUseBlock(id="bbb", command="pwd")

你返回:   tool_result(tool_use_id="aaa", content="file1 file2")
           tool_result(tool_use_id="bbb", content="/home/user")
```

## 7. subprocess.run — 在 Python 里执行命令

### 7.1 基本用法

```python
result = subprocess.run(
    "ls -la",              # 命令字符串
    shell=True,            # 必须！用 shell 解释执行
    capture_output=True,   # 捕获 stdout 和 stderr
    text=True              # 输出为字符串（不是 bytes）
)
```

### 7.2 CompletedProcess 对象

| 属性 | 说明 |
|------|------|
| `result.stdout` | 标准输出（字符串） |
| `result.stderr` | 标准错误（字符串） |
| `result.returncode` | 退出码，0 表示成功 |
| `result.args` | 执行的命令 |

**踩坑：** `result` 本身是 CompletedProcess 对象，不是字符串。直接当字符串用会出 bug。

## 8. Agent Loop 完整模式

把以上所有拼起来：

```python
query = input("你: ")
messages = [{"role": "user", "content": query}]

while True:
    # 1. 调 API（消息 + 工具一起发）
    response = client.messages.create(
        model=MODEL, max_tokens=8000, tools=tools, messages=messages
    )

    # 2. LLM 回复追加到历史
    messages.append({"role": "assistant", "content": response.content})

    # 3. 不是工具调用就退出
    if response.stop_reason != "tool_use":
        for block in response.content:
            if hasattr(block, "text"):
                print(block.text)
        break

    # 4. 执行工具，收集结果
    results = []
    for block in response.content:
        if block.type == "tool_use":
            result = subprocess.run(
                block.input["command"], shell=True,
                capture_output=True, text=True
            )
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result.stdout
            })

    # 5. 结果作为 user 消息追加，循环继续
    messages.append({"role": "user", "content": results})
```

**不到 30 行，这就是整个 Agent。** 后面 11 节课都在这个循环上叠加机制。

## 9. 踩坑记录

| 坑 | 表现 | 原因 | 解决 |
|----|------|------|------|
| 尾逗号变元组 | tool_use_id 变成 `("abc",)` | `x = value,` 在 Python 里是元组 | 删掉尾逗号 |
| CompletedProcess 当字符串 | content 传入对象而非文字 | `subprocess.run()` 返回的是对象 | 用 `.stdout` 取文本 |
| subprocess 不加 shell=True | `FileNotFoundError` | 默认不走 shell 解释 | 加 `shell=True` |
| message.content.append() | 追加到响应对象里 | 混淆了 response.content 和独立 messages 列表 | 用独立的 messages 列表管理历史 |
| 只追加 results[-1] | 丢失多工具调用结果 | LLM 可能一次调用多个工具 | 追加整个 results 列表 |

## 10. 一句话总结

**Agent loop = while True + stop_reason 判断。LLM 说用工具就执行并喂回，说停就停。你的代码是执行者，LLM 是决策者。**