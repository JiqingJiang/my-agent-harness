# My Agent Harness

从零手搓 Agent Harness 的学习记录。每个小节独立实现，代码自己写，笔记自己总结。

## 项目结构

```
├── utils.py                          # 共用工具：彩色打印 + 文件日志
├── s01-agent-loop/s01_agent_loop.py  # 循环：模型与真实世界的第一道连接
├── s02-tool-use/s02_tool_use.py      # 多工具 + Dispatch Map
├── s03-todo-write/                   # 计划：先列步骤再动手
├── s04-subagent/                     # 子 agent：独立上下文
├── s05-skill-loading/                # 按需加载知识
├── s06-context-compact/              # 上下文压缩
├── s07-task-system/                  # 任务系统
├── s08-background-tasks/             # 后台任务
├── s09-agent-teams/                  # Agent 团队
├── s10-team-protocols/               # 团队协议
├── s11-autonomous-agents/            # 自治 Agent
├── s12-worktree-task-isolation/      # Worktree 隔离
├── final/                            # 最终完整版
└── notes/                            # 每节踩坑笔记
```

## 学习来源

基于 [learn-claude-code](https://github.com/anthropics/learn-claude-code) 项目，但所有代码均为从零手搓，非抄源码。

## 环境配置

```bash
cp .env.example .env
# 填入 ANTHROPIC_BASE_URL, MODEL_ID, ANTHROPIC_API_KEY
pip install -r requirements.txt
```

## 进度

| 节 | 状态 | 日期 |
|----|------|------|
| s01 Agent Loop | 完成 | 2026-04-26 |
| s02 Tool Use | 完成 | 2026-04-26 |
| s03-s12 | 进行中 | — |