---
name: init
description: 初始化项目——扫描工作区文件，生成项目概要写入 .agents/AGENTS.md
short_description: 初始化项目并生成概要
type: prompt
use_sub_agent: true
sub_agent_name: assistant
---
请对当前 workspace 进行初始化扫描，了解项目概要情况,编写.agents/AGENTS.md。

## 任务步骤

### 1. 探索项目结构
- 使用 `tree_dir` 工具查看项目顶级目录结构
- 浏览 `pyproject.toml`、`README.md`、`package.json`（如有）等元信息文件

### 2. 了解核心模块
- 如果项目没有README文件，或者README文件介绍不详细，则扫描并阅读核心模块的核心代码
- 不需要了解所有细节，逻辑类似的文件只需要阅读一两个就行

### 3. 编写概要文件
将了解到的项目信息以 Markdown 格式写入 `.agents/AGENTS.md` 文件，内容包括：

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

请确保 `.agents/AGENTS.md` 文件内容精简（不超过200行）、结构清晰，能帮助新开发者快速了解整个项目。
