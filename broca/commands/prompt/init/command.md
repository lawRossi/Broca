---
name: init
description: Initialize project by reading workspace files and writing a summary to ./agents/AGENTS.md
type: prompt
use_sub_agent: true
sub_agent_name: sub-agent
---
请对当前 workspace 进行初始化扫描，了解项目概要情况。

## 任务步骤

### 1. 探索项目结构
- 使用 `tree_dir` 工具查看项目顶级目录结构（max_depth=3）
- 浏览 `pyproject.toml`、`README.md`、`package.json`（如有）等元信息文件

### 2. 深入了解核心模块
- 读取 `broca/` 目录下的核心 Python 模块，了解项目的架构和功能模块
- 阅读 `configs/configs.json` 了解配置
- 阅读 `docs/` 下的设计文档，了解项目定位

### 3. 编写概要文件
将了解到的项目信息以 Markdown 格式写入 `./agents/AGENTS.md` 文件，内容包括：

```markdown
# {项目名称}

## 项目概述
- 项目定位与目标
- 技术栈

## 项目结构
- 目录结构说明
- 各模块功能

## 核心功能
- 主要功能模块介绍
- 关键设计点

## 快速开始
- 如何安装、配置、运行
```

请确保 `./agents/AGENTS.md` 文件内容详实、结构清晰，能帮助新开发者快速了解整个项目。
