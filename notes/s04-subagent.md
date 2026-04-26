# s04: Subagent — 子 Agent 与上下文隔离

> 来源：learn-claude-code s04，邪修模式从零手搓。

## 1. s04 解决什么问题？

s01-s03 的 agent 只有一个 `messages` 列表。随着对话越来越长：

```
messages = [
    用户问题,
    LLM 回复,
    tool_result (read_file 返回了一整个文件),
    LLM 回复,
    tool_result (bash 执行了 ls -la),
    ...  // 30 轮之后，上下文已经很大了
]
```

**问题**：上下文越大，LLM 越容易"分心"——记不住最初的目标，重复做事，或遗漏步骤。

**s04 的解决方案**：主 agent 可以**派生子 agent**，子 agent 有自己独立的 `messages`（干净的上下文），做完任务后只把**摘要**返回给主 agent。

```
主 agent messages=[历史对话...]
    → 派生子 agent → 子 agent messages=[] (干净的)
                    → 子 agent 执行 30 轮工具调用
                    → 子 agent 返回一段摘要
主 agent messages=[历史对话... + 子 agent摘要]  // 只多了一小段文字
```

**核心洞察**：30 次工具调用的中间过程全部丢弃，只保留最终结论。这就是**摘要压缩**——用信息损失换取上下文清晰度。

## 2. 架构设计

### 2.1 父子 agent 的区别

| 维度 | 主 agent (Parent) | 子 agent (Child) |
|------|-------------------|------------------|
| messages | 累积的完整对话 | 每次从头开始，干净 |
| 工具 | base + todo + task | 只有 base（不能列计划、不能再派生） |
| system prompt | 引导列计划和派生 | 简洁：执行任务，返回摘要 |
| 循环 | while True（用户交互） | for range(30)（自动执行） |
| 返回值 | 打印给用户看 | 返回文本摘要给主 agent |

### 2.2 为什么子 agent 不能再派生子 agent？

```
主 agent → 子 agent → 孙子 agent → ...  // 指数级 token 消耗
```

如果允许递归派生：
- 一个 5 层深的子 agent 链可能消耗 5x30=150 次 API 调用
- 每层摘要都有信息损失，深层子 agent 拿到的信息极其稀疏
- 无法预测总 token 消耗，成本不可控

**原则**：主 agent 负责任务拆分和调度，子 agent 只负责执行具体任务。

### 2.3 文件系统共享，上下文隔离

主 agent 和子 agent：
- **共享**：文件系统（子 agent 可以读写主 agent 创建的文件）
- **隔离**：对话历史（子 agent 看不到主 agent 之前聊了什么）

这允许真实协作——主 agent 创建文件，子 agent 读取和修改，但互不污染上下文。

## 3. 代码实现

### 3.1 工具列表拆分

**避免重复定义的关键技巧**：

```python
# 基础工具（定义一次）
base_tools = [bash, read_file, write_file, edit_file]

# todo 和 task 单独定义
todo_tool = {...}
task_tool = {...}

# 组合
parent_tools = base_tools + [todo_tool, task_tool]  # 主 agent 全部
child_tools = base_tools                              # 子 agent 只有基础
```

不再复制粘贴工具定义。`base_tools` 定义一次，通过列表拼接组合出不同角色可用的工具集。

### 3.2 task 工具的 schema

```python
task_tool = {
    "name": "task",
    "description": "派生一个子 agent 执行子任务。子 agent 有独立的上下文，完成后返回摘要。",
    "input_schema": {
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
        "required": ["prompt"]
    }
}
```

输入只有一个 `prompt`（字符串），就是给子 agent 的任务描述。极其简单——复杂性全在 `run_subagent` 里。

### 3.3 Dispatch Map 用 ** 合并

```python
BASE_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
}

PARENT_HANDLERS = {
    **BASE_HANDLERS,      # ** 解包，展开基础 handler
    "todo": run_todo,
    "task": run_task,
}
```

`**` 解包语法：把一个字典的键值对展开到新字典里。不用重复写四行基础 handler。

**注意**：`run_task` 必须在 `PARENT_HANDLERS` 之前定义，否则 Pylance 会报"未定义"。虽然 Python 运行时没问题（字典存的是引用，调用时才解析），但代码顺序影响可读性。

### 3.4 run_subagent 的实现

```python
def run_subagent(prompt: str) -> str:
    sub_messages = [{"role": "user", "content": prompt}]  # 干净的上下文

    for _ in range(30):  # 安全限制：最多 30 轮
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=SUBAGENT_SYSTEM_PROMPT,
            tools=child_tools,     # 子 agent 的工具集
            messages=sub_messages
        )

        sub_messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        # 执行工具
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = BASE_HANDLERS[block.name]
                output = handler(**block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)[:50000]  # 截断防上下文爆炸
                })
        sub_messages.append({"role": "user", "content": results})

    # 提取最终文本摘要
    text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    return text or "(no summary)"
```

关键点：
1. **`messages = [{"role": "user", "content": prompt}]`** — 初始化时只有任务描述，没有历史
2. **`for _ in range(30)`** — 用 for 替代 while True，最多 30 轮自动退出
3. **`str(output)[:50000]`** — 单次工具输出截断到 50KB，防止单个大文件撑爆上下文
4. **`"".join(block.text ...)`** — 提取最后一个 response 里的所有文本块拼接成字符串

### 3.5 return 值的坑

```python
# ✗ 错误：返回的是 API 对象列表
return messages[-1].content    # 这是 [TextBlock(...), ...]

# ✓ 正确：提取文本拼接成字符串
text = "".join(
    block.text for block in response.content if hasattr(block, "text")
)
return text or "(no summary)"
```

`messages[-1].content` 是 API 返回的 content 列表（TextBlock / ToolUseBlock 对象），不是字符串。主 agent 拿到这个结果后要喂回 API，API 期望的是字符串。

### 3.6 run_task — task 工具的 handler

```python
def run_task(prompt: str) -> str:
    cprint("tool_cmd", f"[subagent] {prompt[:60]}...")
    result = run_subagent(prompt)
    cprint("tool_out", f"[subagent result] {result[:200]}...")
    return result
```

run_task 只是 run_subagent 的包装层，加了终端打印让用户能看到子 agent 的活动。实际的子 agent 逻辑全在 run_subagent 里。

### 3.7 System Prompt 区分

```python
SYSTEM_PROMPT = """
  - 面对多步任务时，**必须**先用 todo 工具列出计划
  - 开始执行某一步前，把它标记为 in_progress
  - 完成后标记为 completed
  - 列完计划后立即开始执行，不要等待用户确认
  - 可以使用 task 工具派生子 agent 执行具体子任务"""

SUBAGENT_SYSTEM_PROMPT = "你是一个子 agent。执行给定的任务，完成后返回一段简洁的摘要。"
```

主 agent 的 prompt 详细（引导行为），子 agent 的 prompt 简洁（只说做什么）。

## 4. LLM 什么时候用 task 工具？

**重要认知：工具是能力，LLM 自己决定什么时候用。**

实测发现：
- 简单任务（"当前目录有什么文件"）→ LLM 直接用 bash ls，不派生
- 中等任务（"创建一个计算器"）→ LLM 用 todo 列计划，但自己执行，不派生
- 复杂任务（多文件重构、大规模探索）→ LLM 更可能选择派生

这是正常行为，不是 bug。生产级的 Claude Code 也是这样——LLM 有判断力，它评估后觉得直接做更高效就不派生。

**s03 的"必须先用 todo"改成 s04 的"必须"后确实生效了**——LLM 开始主动调用 todo。但 task 工具的措辞用的是"可以"，因为不是所有任务都值得派生。

## 5. 数据流图

```
用户输入
  ↓
主 agent (messages 累积)
  ├─ 调用 todo → 列计划
  ├─ 调用 bash/read/write/edit → 直接执行
  └─ 调用 task → 触发 run_subagent
                    ↓
              子 agent (messages 干净)
                ├─ 调用 bash/read/write/edit
                ├─ 最多 30 轮
                └─ 返回文本摘要
                    ↓
              摘要作为 tool_result 返回给主 agent
  ↓
主 agent 继续执行下一步
  ↓
最终文本回复给用户
```

## 6. s03 → s04 对比

| 组件 | s03 | s04 |
|------|-----|-----|
| 工具数量 | 5 (base + todo) | 6 (+ task) |
| 上下文 | 单一 messages | 父子隔离 |
| 任务执行 | 主 agent 自己做 | 可以派生子 agent |
| 上下文膨胀 | 随对话线性增长 | 子 agent 的工作被摘要压缩 |
| 工具定义 | 一个 tools 列表 | base_tools + 组合 |
| Handler | 一个 TOOL_HANDLERS | BASE_HANDLERS + PARENT_HANDLERS |
| 循环安全 | while True（无限） | 子 agent for range(30)（有限） |

## 7. 踩坑记录

| 坑 | 表现 | 原因 | 解决 |
|----|------|------|------|
| 子 agent messages 为空 | API 报错或子 agent 不知道做什么 | `messages = []` 没有任务描述 | 初始化时加上 `[{"role": "user", "content": prompt}]` |
| return messages[-1].content | 主 agent 拿到 API 对象，不是字符串 | content 是 TextBlock/ToolUseBlock 列表 | 用 `"".join(block.text for block in ...)` 提取文本 |
| run_task 定义在 PARENT_HANDLERS 后 | Pylance 报"未定义" | 字典创建时引用了还没定义的函数 | 把函数定义挪到 dispatch map 前面 |
| 工具定义重复 | base_tools 复制了两份 | 主 agent 和子 agent 各写了一份工具 | 抽出 base_tools，用列表拼接组合 |
| 子 agent 用了主 agent 的 tools | 子 agent 可以调 todo 和 task | `run_subagent` 里 `tools=tools` 用了主 agent 的 | 改成 `tools=child_tools` |
| 子 agent while True 无限循环 | 理论上永远不会停 | 没有安全退出机制 | 改成 `for _ in range(30)` |
| 单次工具输出太大 | 上下文被一个大文件撑满 | read_file 读了一个大文件返回全文 | `str(output)[:50000]` 截断 |

## 8. 一句话总结

**子 agent = 独立上下文 + 摘要返回。用信息损失换取上下文清晰度。30 次工具调用的中间过程全部丢弃，只保留最终结论。**