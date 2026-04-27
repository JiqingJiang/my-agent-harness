# s05: Skill Loading — 按需加载知识

> 来源：learn-claude-code s05，邪修模式从零手搓。

## 1. s05 解决什么问题？

s04 的 agent 能派生子 agent 了，但 agent 本身是"裸"的——没有专业知识。

比如你想让 agent 做代码审查，它需要知道审查清单：检查安全漏洞、性能问题、错误处理……这些知识从哪来？

**笨办法**：全塞进 system prompt。

```
system_prompt = """
你是编程助手。
【代码审查知识】
- 检查 SQL 注入
- 检查 XSS
- ...（2000 token）
【PDF 处理知识】
- 使用 pdftotext ...
- ...（2000 token）
【Git 工作流知识】
- ...（2000 token）
"""
```

**三个问题**：
1. **浪费 token**：10 个 skill × 2000 token = 20000 token，大多数跟当前任务无关
2. **上下文污染**：让 LLM 看到不相关的知识，反而干扰判断
3. **缓存失效**：system prompt 每次变，API 的 prompt cache 就废了

## 2. 核心方案：两层注入

```
Layer 1（System Prompt，始终存在，~50 token/skill）：
  Skills available:
    - pdf: 处理 PDF 文件
    - code-review: 代码审查
    - agent-builder: 设计 agent

Layer 2（Tool Result，按需加载，~2000 token/skill）：
  LLM 调用 load_skill("code-review")
    → tool_result 返回 code-review 的完整审查清单
    → LLM 带着这些知识开始执行
```

**核心思想**：system prompt 只放目录（便宜、静态、可缓存），真正的内容等 LLM 需要时再通过工具返回。

## 3. 架构设计

### 3.1 SkillLoader 类

```
SkillLoader
├── __init__(skills_dir)     # 初始化，扫描目录
├── _parse_frontmatter(text) # 分割 YAML 元数据和 Markdown body
├── _load_all(skills_dir)    # 扫描所有 SKILL.md，存入 self.skills
├── get_descriptions()       # Layer 1：返回所有 skill 的简短描述
└── get_content(name)        # Layer 2：返回某个 skill 的完整内容
```

### 3.2 SKILL.md 文件格式

每个 skill 是一个 `SKILL.md` 文件，包含 YAML frontmatter + Markdown body：

```markdown
---
name: code-review
description: 执行代码审查，检查安全、性能和可维护性
---

# Code Review Skill

## Review Checklist
### 1. Security (Critical)
- 检查注入漏洞：SQL、命令、XSS、模板注入
...
```

**frontmatter**：元数据（name、description），给 Layer 1 用。
**body**：完整专业知识，给 Layer 2 用。

### 3.3 self.skills 的数据结构

```python
self.skills = {
    "pdf": {
        "name": "pdf",
        "description": "处理 PDF 文件...",
        "body": "# PDF Processing Skill\n..."  # 完整知识内容
    },
    "code-review": {
        "name": "code-review",
        "description": "执行代码审查...",
        "body": "# Code Review Skill\n..."
    },
}
```

每条 skill 存三个字段，同时满足 `get_descriptions()`（要 name + description）和 `get_content(name)`（要 body）的需求。

## 4. 代码实现

### 4.1 _parse_frontmatter：YAML 分割

```python
def _parse_frontmatter(self, text: str) -> tuple:
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, match.group(2).strip()
```

关键点：
1. `re.DOTALL`：让 `.` 匹配换行符，否则只能匹配单行
2. `yaml.safe_load(match.group(1))`：解析 YAML 文本为字典
3. `or {}`：yaml.safe_load 对空内容返回 None，需要兜底
4. 没有匹配到 `---` 时返回空字典 + 原文（容错）

### 4.2 _load_all：扫描目录

```python
def _load_all(self, skills_dir: str):
    for f in sorted(Path(skills_dir).rglob("SKILL.md")):
        text = f.read_text()
        meta, body = self._parse_frontmatter(text)
        name = meta.get("name", f.parent.name)  # 兜底用目录名
        desc = meta.get("description", "No description")
        self.skills[name] = {"name": name, "description": desc, "body": body}
```

关键点：
1. `Path(skills_dir).rglob("SKILL.md")`：递归搜索所有 SKILL.md
2. `sorted()`：保证加载顺序一致
3. `meta.get("name", f.parent.name)`：name 优先从 frontmatter 取，没有就用目录名兜底

### 4.3 get_descriptions 和 get_content

```python
def get_descriptions(self) -> str:
    lines = []
    for name, skill in self.skills.items():
        lines.append(f"  - {name}: {skill['description']}")
    return "\n".join(lines)

def get_content(self, name: str) -> str:
    skill = self.skills.get(name)
    if not skill:
        return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
    return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
```

关键点：
1. `get_descriptions` 返回纯文本列表，适合拼进 system prompt
2. `get_content` 用 XML 标签包裹 skill body，让 LLM 清楚区分知识边界
3. 未知 skill 名返回错误信息 + 可用列表，而不是抛异常

### 4.4 load_skill 工具定义

```python
load_skill = {
    "name": "load_skill",
    "description": "按需加载专业知识。面对不熟悉的领域（如代码审查、PDF处理、MCP构建等）时，先加载对应 skill 获取专家级指引。",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"]
    }
}
```

### 4.5 handler 和 dispatch map

```python
def run_load_skill(name: str) -> str:
    return SKILL_LOADER.get_content(name)

BASE_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "load_skill": run_load_skill,  # 子 agent 也能用
}
```

**设计决策**：`load_skill` 放 `BASE_HANDLERS`，子 agent 也能加载专业知识。因为子 agent 做具体任务时同样可能需要领域知识。

### 4.6 System Prompt 集成

```python
SKILL_LOADER = SkillLoader("skills")

SYSTEM_PROMPT = f"""
  - 面对多步任务时，**必须**先用 todo 工具列出计划
  - ...
  - 可以使用 load_skill 工具加载专业知识
  Skills available:
{SKILL_LOADER.get_descriptions()}
"""
```

关键点：
1. `SYSTEM_PROMPT` 变成 **f-string**，嵌入动态的 skill 描述
2. `SKILL_LOADER` 必须在 `SYSTEM_PROMPT` 之前创建（Python 从上往下执行）
3. skill 描述只有 name + description，非常轻量（~50 token/skill）

### 4.7 工具列表更新

```python
parent_tools = base_tools + [todo_tool, task_tool, load_skill]  # 主 agent 全部
child_tools = base_tools + [load_skill]                         # 子 agent 有 load_skill
```

## 5. 工具 Description 写法

工具 description 是写给 LLM 看的 "使用说明书"。写法公式：

**做什么 + 什么时候用 + （可选）跟其他工具的区别**

| 工具 | description |
|------|-------------|
| bash | 执行 bash 命令。用于运行脚本、安装依赖、查看目录结构等系统操作。 |
| read_file | 读取文件内容。查看已有代码、配置文件或日志时使用。 |
| write_file | 创建新文件并写入内容。需要创建新代码文件或配置文件时使用。 |
| edit_file | 精确替换文件中的文本片段。修改现有代码或配置时使用，比全量重写更安全。 |
| todo | 管理任务计划。多步任务开始前先用此工具列出所有步骤，执行中更新状态。 |
| task | 派生子 agent 执行独立的子任务。适合需要大量探索或多文件操作的任务。 |
| load_skill | 按需加载专业知识。面对不熟悉的领域时，先加载对应 skill 获取专家级指引。 |

**关键**：description 要让 LLM 自己判断 "我现在需不需要这个工具"，而不只是说"这个工具能干啥"。

## 6. 数据流图

```
启动时：
  SkillLoader("skills/")
    → 扫描所有 SKILL.md
    → 解析 frontmatter → self.skills
    → get_descriptions() → 拼入 system prompt

运行时：
  用户：帮我审查这段代码
    ↓
  LLM 看到系统提示里有 "code-review: 执行代码审查..."
    ↓
  LLM 判断需要专业知识 → 调用 load_skill("code-review")
    ↓
  handler: SKILL_LOADER.get_content("code-review")
    → 返回 <skill name="code-review"> 完整审查清单 </skill>
    ↓
  LLM 拿到知识，开始执行审查
```

## 7. s04 → s05 对比

| 组件 | s04 | s05 |
|------|-----|-----|
| 工具数量 | 6 (base + todo + task) | 7 (+ load_skill) |
| 专业知识 | 无 | 两层注入 |
| System Prompt | 静态字符串 | f-string + skill 描述 |
| 知识存储 | — | skills/\*/SKILL.md 文件 |
| 知识加载 | — | 按需（load_skill 工具） |
| 缓存友好 | — | system prompt 静态部分可缓存 |

## 8. 踩坑记录

| 坑 | 表现 | 原因 | 解决 |
|----|------|------|------|
| _parse_frontmatter 漏了 self | 方法调用报错 | 写成 `_parse_frontmatter(text)` 而非 `self._parse_frontmatter(text)` | 实例方法第一个参数必须是 self |
| 参数和返回值写反 | 不知道怎么用 | 把 `(meta_dict, body_string)` 写成了参数，实际应该是 `text` 入参，`(meta, body)` 返回值 | 入参是文件全文，返回值是解析后的两个部分 |
| handler 绑了 get_descriptions | load_skill 返回的是目录而不是内容 | `"load_skill": SkillLoader.get_descriptions` 绑错了方法 | 应该绑定一个调用 `get_content(name)` 的 handler 函数 |
| SKILL_LOADER 定义在 SYSTEM_PROMPT 之后 | f-string 报 NameError | Python 从上往下执行，SYSTEM_PROMPT 定义时 SKILL_LOADER 还不存在 | 把 SKILL_LOADER 定义挪到 SYSTEM_PROMPT 之前 |
| 没有创建 SkillLoader 实例 | import 了但没实例化 | `from SkillLoader import *` 只导入了类 | 需要显式创建实例：`SKILL_LOADER = SkillLoader("skills")` |

## 9. 一句话总结

**Skill Loading = 知识不预加载，按需注入。System prompt 只放目录（静态可缓存），LLM 需要时通过 load_skill 工具获取完整知识。用延迟加载换取 token 效率和缓存命中率。**