# s02: Tool Use — 多工具 + Dispatch Map

> 来源：learn-claude-code s02，邪修模式从零手搓。

## 1. s02 解决什么问题？

s01 只有 bash 一个工具，所有操作都走 shell。问题：
- `cat` 读文件截断不可预测
- `sed` 替换遇到特殊字符就崩
- 每次 bash 调用都是不受约束的安全面

**专用工具（read_file, write_file, edit_file）可以在工具层面做安全控制。**
**关键洞察：加工具不需要改循环。**

## 2. Dispatch Map — s02 的核心

### 2.1 什么是 Dispatch Map？

一个字典，把工具名映射到处理函数：

```python
TOOL_HANDLERS = {
    "bash":      run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
}
```

循环里的执行代码从 s01 的硬编码：
```python
# s01: 硬编码 bash
subprocess.run(block.input["command"], ...)
```

变成 s02 的字典查找：
```python
# s02: dispatch map 查找
handler = TOOL_HANDLERS[block.name]
output = handler(**block.input)
```

**一行查找替代任何 if/elif 链。加新工具 = 加函数 + 加一行注册，循环永远不变。**

### 2.2 `**block.input` 是什么？

`block.input` 是一个字典，比如 `{"path": "hello.py", "limit": 10}`。
`**block.input` 把它展开成关键字参数：`run_read(path="hello.py", limit=10)`。

### 2.3 参数名必须和 input_schema 的 key 完全一致

**这是 s02 最容易踩的坑。**

工具定义里 `properties` 的 key 名，必须和函数参数名一一对应：

```python
# 工具定义
"properties": {"command": {"type": "string"}}

# 函数签名 — 参数名必须是 command，不能是 cmd
def run_bash(command: str):   # ✓
def run_bash(cmd: str):       # ✗ handler(**block.input) 会报 unexpected keyword argument
```

如果不一致，`**block.input` 展开后参数名对不上，直接 TypeError。

## 3. 四个工具的实现细节

### 3.1 run_bash(command)

和 s01 一样，subprocess 执行命令。不变。

### 3.2 run_read(path, limit=None)

```python
def run_read(path: str, limit=None):
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"
```

- `open(path)` 默认是读模式（`"r"`），不需要指定
- 不需要 subprocess，直接 Python 读文件
- `limit` 参数暂时没实现（预留的，后面可以加行数限制）

### 3.3 run_write(path, content)

```python
def run_write(path: str, content: str):
    try:
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"Wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error: {e}"
```

三个关键点：
- **`"w"` 模式**：`open(path, "w")` 才是写模式，默认 `"r"` 是读模式
- **`parents=True, exist_ok=True`**：目录不存在自动创建，已存在不报错
- 返回写入字节数，让 LLM 知道写成功了

### 3.4 run_edit(path, old_text, new_text)

```python
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
```

分三步：读 → 找 → 换。

关键点：
- **`content.replace(old, new, 1)`**：第三个参数 `1` 表示只替换第一个匹配。防止不小心替换了多处
- **先检查 `old_text not in content`**：如果找不到目标文字，立刻返回错误，而不是无意义地写回原文件
- 读用 `"r"`，写用 `"w"`

## 4. 所有处理函数必须 try/except

**这是 s02 的核心工程原则。**

Agent 循环里，如果任何一个 handler 崩溃了，整个程序就挂了。
正确的做法：handler 永远返回字符串，成功返回结果，失败返回错误信息。

```python
def run_xxx(...):
    try:
        # 正常逻辑
        return "成功结果"
    except Exception as e:
        return f"Error: {e}"   # 返回错误字符串，不是抛异常
```

LLM 拿到错误信息后，会自己想办法纠正（比如文件名打错了，它会先 ls 找正确文件名）。
这就是 agent 的容错能力 — **错误不崩溃，而是变成信息流回 LLM。**

## 5. 工具定义的格式规范

每个工具定义是一个字典，包含三个字段：

```python
{
    "name": "tool_name",           # 工具名，LLM 调用时引用
    "description": "做什么的",      # LLM 根据 description 决定何时用
    "input_schema": {              # JSON Schema 格式
        "type": "object",
        "properties": {
            "param1": {"type": "string"},
            "param2": {"type": "integer"},
        },
        "required": ["param1"]
    }
}
```

注意：**字典的键值对之间不能漏逗号**，尤其是 `properties` 和 `required` 之间。

## 6. LLM 如何选择工具？

LLM 看到所有工具的 name + description，根据用户的问题自己判断用哪个。
- "读一下 xxx" → `read_file`
- "当前目录有什么" → `bash`（执行 ls）
- "创建一个 xxx" → `write_file`
- "把 xxx 改成 yyy" → `edit_file`

如果用户打错了（比如文件名不对），LLM 会：
1. 先用错误信息调用工具
2. 拿到 Error 返回
3. 自己决定用 bash ls 找正确文件名
4. 再用正确参数重试

**这个纠错行为是 agent loop 自带的，不需要你写额外代码。**

## 7. 踩坑记录

| 坑 | 表现 | 原因 | 解决 |
|----|------|------|------|
| 函数参数名不一致 | `TypeError: got an unexpected keyword argument 'command'` | `run_bash(cmd)` 但 input_schema 定义的是 `command` | 参数名和 schema key 必须一致 |
| 字典漏逗号 | `SyntaxError: invalid syntax` | `properties: {...}` 后面没逗号直接接 `required` | 检查所有字典项之间的逗号 |
| run_write 用了读模式 | 写入不生效 | `open(path)` 默认是 `"r"` 模式 | 改成 `open(path, "w")` |
| run_read 没有异常处理 | FileNotFoundError 崩溃整个程序 | 文件不存在时直接抛异常 | 加 try/except，返回错误字符串 |
| run_edit 没检查 old_text | 无意义替换 | old_text 不在文件里，replace 返回原字符串 | 先 `if old_text not in content` 检查 |

## 8. s01 → s02 对比

| 组件 | s01 | s02 |
|------|-----|-----|
| 工具数量 | 1 (bash) | 4 (bash, read, write, edit) |
| 工具执行 | 硬编码 subprocess | TOOL_HANDLERS 字典查找 |
| 循环体 | — | **一行没改** |
| 错误处理 | 无 | 所有 handler 都有 try/except |

## 9. 一句话总结

**加工具 = 加 handler 函数 + 加 input_schema + 加一行注册。循环永远不变。dispatch map 让扩展变成声明式的。**