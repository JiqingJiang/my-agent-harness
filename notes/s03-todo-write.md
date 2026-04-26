# s03: Todo Write — 让 Agent 先列计划再动手

> 来源：learn-claude-code s03，邪修模式从零手搓。

## 1. s03 解决什么问题？

s02 的 agent 已经能执行多步任务，但有一个严重问题：**Agent 在多步任务中会"漂移"**。

- 忘了某个步骤
- 重复做同一件事
- 做着做着跑题了

**核心洞察**：计划不应该只存在于 LLM 的脑子里（上下文窗口中），而应该**外化为可见的、可追踪的状态**。

类比：LLM 脑子里想"今天要做 A、B、C"是内部推理；把这些写到便利贴上贴在显示器旁边，才是 todo 工具做的事。

## 2. Todo 工具的设计

### 2.1 全量替换，不是追加

**最关键的设计决策。**

LLM 每次调用 todo 工具，传入的是**完整的 todo 列表**，而不是追加一条新任务。

```python
# 正确：全量替换
def run_todo(items):
    todolist.clear()
    todolist.extend(items)
    return f"Todo updated ({len(todolist)} items): " + str(todolist)

# 错误：追加
def run_todo(content, status):
    todolist.append({"content": content, "status": status})
    return todolist
```

为什么不能追加？因为 LLM 需要更新已有任务的状态（pending → in_progress → completed），追加模式做不到更新。

**LLM 的使用流程：**
1. 第一次：传入 `[{A, pending}, {B, pending}, {C, pending}]` → 创建计划
2. 第二次：传入 `[{A, in_progress}, {B, pending}, {C, pending}]` → 开始执行 A
3. 第三次：传入 `[{A, completed}, {B, in_progress}, {C, pending}]` → A 完成，开始 B

### 2.2 Schema 定义：嵌套数组

```python
{
    "name": "todo",
    "description": "更新任务列表。传入完整的 items 数组，每次全量替换。",
    "input_schema": {
        "type": "object",
        "properties": {"items": {
            "type": "array",
            "items": {                        # ← 这是 JSON Schema 关键字
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
```

注意这里有**两个 `items`**：
- 第一个 `"items"` 是**参数名**（LLM 传过来的字段名）
- 第二个 `"items"` 是 **JSON Schema 关键字**（定义数组元素的类型）

不要搞混。

### 2.3 三种状态

| 状态 | 含义 | 什么时候设置 |
|------|------|-------------|
| `pending` | 还没做 | 创建计划时，所有任务都是 pending |
| `in_progress` | 正在做 | 开始执行某一步前设置 |
| `completed` | 做完了 | 完成后设置 |

理想情况下，同时只有一个任务是 `in_progress`（LLM 专注做一件事）。

### 2.4 全局列表的修改方式

**踩坑：`todolist = items` 不行。**

```python
todolist = []    # 全局列表

def run_todo(items):
    todolist = items    # ✗ 这只是创建了一个局部变量，全局列表没变
    return todolist

def run_todo(items):
    global todolist      # 可以用 global，但不推荐
    todolist = items
    return todolist

def run_todo(items):
    todolist.clear()     # ✓ 推荐方式：原地修改全局列表
    todolist.extend(items)
    return f"Todo updated ({len(todolist)} items): " + str(todolist)
```

`clear()` + `extend()` 是**修改列表对象本身**，不需要 `global` 关键字。

## 3. System Prompt — 引导 LLM 使用 todo

### 3.1 为什么需要 System Prompt？

加了 todo 工具后，LLM 不会自动知道要先用它列计划。你给了它一把锤子，但它不知道什么时候该用。

**工具只是能力，System Prompt 才是行为引导。**

### 3.2 System Prompt 怎么传？

**踩坑：`messages` 里不能放 system 角色。**

```python
# ✗ 某些 API 不接受 messages 里有 system 角色
messages.append({"role": "system", "content": SYSTEM_PROMPT})
# 报错：unknown variant `system`, expected `user` or `assistant`

# ✓ 用 client.messages.create() 的 system 参数单独传
response = client.messages.create(
    model=MODEL,
    max_tokens=8000,
    system=SYSTEM_PROMPT,    # 单独传，不放在 messages 里
    tools=tools,
    messages=messages
)
```

**原因**：Anthropic 官方 API 支持两种方式传 system prompt，但某些兼容 API（如用户使用的第三方 API）只支持 `system` 参数方式，不支持在 `messages` 里放 `system` 角色。

### 3.3 System Prompt 内容

```python
SYSTEM_PROMPT = """
  - 面对多步任务时，先用 todo 工具列出计划
  - 开始执行某一步前，把它标记为 in_progress
  - 完成后标记为 completed
  - 列完计划后立即开始执行，不要等待用户确认。"""
```

**最后一句非常关键。** 没有这句时，LLM 列完计划就会停下来等待用户确认（stop_reason 变成 end_turn），不会自动开始执行。因为 LLM 默认行为是"我列完计划了，你来确认"。

加了"列完计划后立即开始执行"之后，LLM 列完计划会接着调用 write_file、bash 等工具去执行第一步。

### 3.4 Agent 循环中停下来不执行的问题

这是 s03 最常见的调试场景：

**现象**：LLM 调用了 todo 工具，拿到结果后，直接回复文字，然后 agent 循环 break，回到用户输入。

**原因**：LLM 的 stop_reason 是 `end_turn` 而不是 `tool_use`。LLM 选择了"说话"而不是"继续调用工具"。

**排查思路**：
1. 看 system prompt 是否明确要求"列完计划后立即执行"
2. 看 todo 工具的返回值是否清晰（如果返回的是 Python 列表的 str()，LLM 可能理解不好）
3. 看 LLM 的回复内容——它是不是在"汇报计划"而不是"执行计划"

## 4. 催促系统（Nag Reminder）— 概念记录

**这一节我们只了解了概念，没有实现。**

### 4.1 问题

即使有 todo 工具和 system prompt，LLM 在执行多轮之后可能"漂移"——它忙着执行具体任务，忘了更新 todo 状态，甚至忘了自己的计划。

### 4.2 解决方案：轮次计数器 + 提醒注入

在 agent loop 里加一个计数器 `rounds_since_todo`：
- 每轮循环，如果 LLM 调用了 todo → 计数器归零
- 每轮循环，如果 LLM 没调用 todo → 计数器 +1
- 当计数器 >= 3 → 在 tool_result 里注入一条提醒：`<reminder>Update your todos.</reminder>`

```python
rounds_since_todo = 0

# 在工具执行循环中：
used_todo = any(block.name == "todo" for block in response.content if block.type == "tool_use")
rounds_since_todo = 0 if used_todo else rounds_since_todo + 1

if rounds_since_todo >= 3:
    results.append({"type": "text", "text": "<reminder>请更新你的任务列表状态。</reminder>"})
```

**本质**：harness 层面对 LLM 的被动监督。不信任 LLM 自己能持续追踪进度，用代码强制提醒。

### 4.3 TodoManager 类（进阶封装）

s03 源码把 todo 列表封装成了一个 `TodoManager` 类，而不是裸的全局列表：

- `update(items)` 方法：验证输入、强制单 in_progress 约束、最大 20 条限制
- `render()` 方法：把 todo 列表渲染成 `[ ]` pending、`[>]` in_progress、`[x]` completed 的可视化格式
- 每次更新后自动 render，让 LLM 和用户都能看到当前进度

**为什么要封装成类？**
- 验证逻辑（单 in_progress、max 20）放在类里，handler 只需要调 `update()`
- render 逻辑统一管理，handler 不需要关心展示格式
- 加新规则只需要改类，不需要改 handler 和循环

## 5. s02 → s03 对比

| 组件 | s02 | s03 |
|------|-----|-----|
| 工具数量 | 4 (bash, read, write, edit) | 5 (+ todo) |
| System Prompt | 无 | 有，引导 LLM 使用 todo |
| 计划能力 | 无，LLM 内部推理 | 外化为可见的 todo 列表 |
| Agent 行为 | 拿到任务直接开干 | 先列计划，再逐步执行 |
| 漂移问题 | 完全无感知 | 可通过 nag reminder 缓解 |

## 6. 踩坑记录

| 坑 | 表现 | 原因 | 解决 |
|----|------|------|------|
| Schema 用了 `"list"` 类型 | LLM 不理解或 API 报错 | JSON Schema 里没有 `"list"` 类型，应该是 `"object"` 里包含 `"array"` 字段 | 改成 `type: "object"`，items 字段 `type: "array"` |
| Schema 两个 `items` 搞混 | 不知道哪个是参数名哪个是类型 | 参数名叫 `items`，JSON Schema 的数组元素定义也叫 `items` | 第一个是参数名（你在 Python 里用 `block.input["items"]` 访问），第二个是 Schema 关键字 |
| `todolist = items` 全局列表没变 | 函数内赋值，全局列表不变 | Python 函数内直接赋值给全局变量名只会创建局部变量 | 用 `clear()` + `extend()` 原地修改 |
| messages 里放 system 角色 | `unknown variant system` 报错 | 某些 API 不支持在 messages 中使用 system 角色 | 用 `client.messages.create(system=...)` 单独传 |
| LLM 列完计划就停下来 | Agent 回到用户输入，不执行 | System prompt 只说了"先列计划"，没说"列完立即执行" | 加一句"列完计划后立即开始执行，不要等待用户确认" |
| Schema 的 properties 漏逗号 | SyntaxError | `properties: {...}` 后面没逗号直接接 `required` | 同 s02，检查字典项之间的逗号 |

## 7. 一句话总结

**工具只是能力，System Prompt 才是行为引导。Todo 工具把 LLM 的计划从"脑子里"搬到"外面来"，让进度可见、可追踪、可纠正。**