# 标准辩论赛 Demo

使用 Round-Table 每轮自定义配置实现的完整辩论赛流程。

## 辩论流程

```
主持人开场
  → 正方立论     ← 每轮指定发言
  → 反方立论     ← 每轮指定发言
  → 自由辩论     ← 双方交替，随机顺序
  → 正方总结     ← 每轮指定发言
  → 反方总结     ← 每轮指定发言
  → 评委点评     ← reviewers 评分
  → 主持人总结
```

## 角色

| 角色　　　　| 名称　 | 职责　　　　　　　　　　 |
| :------------| :-------| :-------------------------|
| moderator　 | 主持人 | 开场、引导流程、宣布结果 |
| participant | 正方　 | 支持议题，立论/驳论/总结 |
| participant | 反方　 | 反对议题，立论/驳论/总结 |
| reviewer　　| 评委　 | 全程观看，打分并点评　　 |

## 评分标准

评委从五个维度评分（每项 1-10 分）：
1. 论点质量
2. 论据支撑
3. 逻辑严密性
4. 反驳能力
5. 表达说服力

## 使用的 Round-Table 特性

| 特性 | 说明 |
|:-----|:-----|
| **每轮自定义 rounds** | 8 个阶段分别指定发言人和顺序 |
| **speakers** | 每轮限定发言人（如仅正方/仅反方） |
| **order: random** | 自由辩论阶段随机交替 |
| **多种角色** | moderator / participant / reviewer |
| **moderator 开场+结束语** | 主持人控制辩论节奏 |

## 使用方法

### 通过 Web UI

1. 启动 Broca 服务
2. 创建「Agent 编排」会话，工作目录指向 `examples/round-table_ai-debate`
3. 提交 `crew_configs/crew.yaml`

## 自定义

### 修改辩题

编辑 `crew.yaml` 中 `blackboard.initial_entries` 下的 `topic` 值。

### 调整辩论流程

修改 `orchestrator.extras.rounds` 列表，可增删阶段或调整顺序。

## 文件结构

```
examples/round-table_ai-debate/
├── README.md
├── crew_configs/
│   └── crew.yaml
└── .agents/
    ├── AGENTS.md
    └── agents/
        ├── moderator.md      # 主持人
        ├── pro.md            # 正方
        ├── con.md            # 反方
        └── judge.md          # 评委
