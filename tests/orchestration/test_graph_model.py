"""
Graph 数据模型单元测试

覆盖：
- NodeType 枚举
- Edge 创建、序列化/反序列化
- Router 创建、序列化/反序列化
- Node 创建（TASK、HUMAN、CREW 类型）、序列化/反序列化
- Graph 编译校验、序列化/反序列化
- GraphBuilder 构建
- 循环检测
"""

import json

import pytest

from broca.orchestration.graph_model import (
    Edge,
    Graph,
    GraphBuilder,
    Node,
    NodeType,
    Router,
)


class TestNodeType:
    """测试 NodeType 枚举"""

    def test_enum_values(self):
        """测试枚举值"""
        assert NodeType.TASK.value == "task"
        assert NodeType.HUMAN.value == "human"
        assert NodeType.CREW.value == "crew"


class TestEdge:
    """测试 Edge 类"""

    def test_create_edge(self):
        """测试创建边"""
        edge = Edge(target="next_node")
        assert edge.target == "next_node"
        assert edge.description == ""
        assert edge.field is None

    def test_conditional_edge(self):
        """测试条件边"""
        edge = Edge(target="node_b", field="status", operator="eq", value="done")
        assert edge.field == "status"
        assert edge.operator == "eq"
        assert edge.value == "done"

    def test_to_dict_simple(self):
        """测试简单边转字典"""
        edge = Edge(target="next", description="route")
        d = edge.to_dict()
        assert d["target"] == "next"
        assert d["description"] == "route"

    def test_to_dict_conditional(self):
        """测试条件边转字典"""
        edge = Edge(target="next", field="x", operator="gt", value=5)
        d = edge.to_dict()
        assert d["field"] == "x"
        assert d["operator"] == "gt"
        assert d["value"] == 5

    def test_from_dict(self):
        """测试从字典恢复"""
        edge = Edge.from_dict({
            "target": "next",
            "description": "go next",
            "field": "status",
            "operator": "eq",
            "value": "ok",
        })
        assert edge.target == "next"
        assert edge.field == "status"

    def test_from_dict_minimal(self):
        """测试从最小字典恢复"""
        edge = Edge.from_dict({"target": "next"})
        assert edge.target == "next"
        assert edge.description == ""


class TestRouter:
    """测试 Router 类"""

    def test_create_router(self):
        """测试创建路由"""
        router = Router(mode="static")
        assert router.mode == "static"

    def test_agent_router(self):
        """测试 Agent 路由"""
        router = Router(mode="agent", evaluator="evaluator_agent", prompt="Choose")
        assert router.evaluator == "evaluator_agent"
        assert router.prompt == "Choose"

    def test_to_dict(self):
        """测试转字典"""
        router = Router(mode="static_then_agent", evaluator="eval")
        d = router.to_dict()
        assert d["mode"] == "static_then_agent"
        assert d["evaluator"] == "eval"

    def test_from_dict(self):
        """测试从字典恢复"""
        router = Router.from_dict({"mode": "agent", "evaluator": "eval", "prompt": "Pick"})
        assert router.mode == "agent"
        assert router.prompt == "Pick"


class TestNode:
    """测试 Node 类"""

    def test_create_task_node(self):
        """测试创建 TASK 节点"""
        node = Node(name="analyze", type=NodeType.TASK, agent="analyst", task="Analyze")
        assert node.name == "analyze"
        assert node.type == NodeType.TASK
        assert node.agent == "analyst"

    def test_create_human_node(self):
        """测试创建 HUMAN 节点"""
        node = Node(name="approve", type=NodeType.HUMAN, question="Approve?", response_field="ok")
        assert node.question == "Approve?"
        assert node.response_field == "ok"

    def test_create_crew_node(self):
        """测试创建 CREW 节点"""
        node = Node(name="team_work", type=NodeType.CREW, crew_ref="research_team")
        assert node.crew_ref == "research_team"

    def test_node_with_edges(self):
        """测试带边的节点"""
        node = Node(name="start", edges=[Edge(target="step1"), Edge(target="step2")])
        assert len(node.edges) == 2

    def test_node_to_dict(self):
        """测试节点转字典"""
        node = Node(name="analyze", type=NodeType.TASK, agent="analyst", task="Do analysis")
        d = node.to_dict()
        assert d["name"] == "analyze"
        assert d["type"] == "task"
        assert d["agent"] == "analyst"

    def test_node_from_dict(self):
        """测试从字典恢复节点"""
        node = Node.from_dict({
            "name": "review", "type": "task", "agent": "reviewer", "task": "Review",
            "edges": [{"target": "done"}],
        })
        assert node.name == "review"
        assert node.type == NodeType.TASK
        assert len(node.edges) == 1

    def test_node_defaults(self):
        """测试默认值"""
        node = Node(name="test")
        assert node.type == NodeType.TASK
        assert node.edges == []
        assert node.max_loop == 0

    def test_node_extras(self):
        """测试额外属性"""
        node = Node(name="test", extras={"key": "value"})
        assert node.extras["key"] == "value"


class TestGraph:
    """测试 Graph 类"""

    def test_create_graph(self):
        """测试创建图"""
        nodes = {
            "start": Node(name="start"),
            "end": Node(name="end"),
        }
        graph = Graph(nodes=nodes, entry="start")
        assert graph.entry == "start"
        assert "start" in graph.nodes

    def test_empty_graph(self):
        """测试空图（无节点）"""
        graph = Graph(nodes={})
        assert graph.nodes == {}

    def test_compile_missing_entry(self):
        """测试编译时入口节点缺失"""
        graph = Graph(nodes={})
        errors = graph.compile()
        assert any("Entry node" in e for e in errors)

    def test_compile_missing_target(self):
        """测试编译时目标节点缺失"""
        nodes = {
            "start": Node(name="start", edges=[Edge(target="missing")]),
        }
        graph = Graph(nodes=nodes, entry="start")
        errors = graph.compile()
        assert any("target" in e for e in errors)

    def test_compile_valid_graph(self):
        """测试有效图编译（单节点）"""
        nodes = {
            "start": Node(name="start"),
        }
        graph = Graph(nodes=nodes, entry="start")
        errors = graph.compile()
        assert len(errors) == 0

    def test_compile_with_unreachable_node(self):
        """测试编译检测到不可达节点"""
        nodes = {
            "start": Node(name="start"),
            "orphan": Node(name="orphan"),
        }
        graph = Graph(nodes=nodes, entry="start")
        errors = graph.compile()
        assert any("Unreachable" in e for e in errors)

    def test_compile_simple_path(self):
        """测试简单路径编译"""
        nodes = {
            "start": Node(name="start", edges=[Edge(target="end")]),
            "end": Node(name="end"),
        }
        graph = Graph(nodes=nodes, entry="start")
        errors = graph.compile()
        assert len(errors) == 0

    def test_compile_human_node_missing_fields(self):
        """测试 HUMAN 节点缺少字段"""
        nodes = {
            "start": Node(name="start", edges=[Edge(target="approve")]),
            "approve": Node(name="approve", type=NodeType.HUMAN),
        }
        graph = Graph(nodes=nodes, entry="start")
        errors = graph.compile()
        assert any("question" in e for e in errors)
        assert any("response_field" in e for e in errors)

    def test_compile_human_node_valid(self):
        """测试有效的 HUMAN 节点"""
        nodes = {
            "start": Node(name="start", edges=[Edge(target="approve")]),
            "approve": Node(name="approve", type=NodeType.HUMAN, question="OK?", response_field="answer"),
        }
        graph = Graph(nodes=nodes, entry="start")
        errors = graph.compile()
        assert len(errors) == 0

    def test_to_dict(self):
        """测试图转字典"""
        nodes = {
            "start": Node(name="start", edges=[Edge(target="end")]),
            "end": Node(name="end"),
        }
        graph = Graph(nodes=nodes, entry="start")
        d = graph.to_dict()
        assert d["entry"] == "start"
        assert "start" in d["nodes"]
        assert "end" in d["nodes"]

    def test_from_dict(self):
        """测试从字典恢复图"""
        data = {
            "entry": "start",
            "nodes": {
                "start": {"name": "start", "type": "task", "edges": [{"target": "end"}]},
                "end": {"name": "end", "type": "task"},
            },
        }
        graph = Graph.from_dict(data)
        assert graph.entry == "start"
        assert "start" in graph.nodes
        assert "end" in graph.nodes
        assert len(graph.nodes["start"].edges) == 1


class TestGraphBuilder:
    """测试 GraphBuilder"""

    def test_from_crew_config_empty(self):
        """测试从空配置构建"""
        from broca.orchestration.crew import CrewConfig, OrchestratorConfig

        config = CrewConfig(
            name="test",
            description="test crew",
            agents=["agent1"],
            orchestrator=OrchestratorConfig(type="pipeline", extras={"graph": None}),
        )
        result = GraphBuilder.from_crew_config(config)
        assert result is None

    def test_graph_serialization_roundtrip(self):
        """测试序列化往返"""
        nodes = {
            "start": Node(name="start", edges=[Edge(target="end")]),
            "end": Node(name="end"),
        }
        graph = Graph(nodes=nodes, entry="start")
        # 注意：to_dict 会包含 entry 信息
        d = graph.to_dict()
        assert "start" in d["nodes"]
        assert "end" in d["nodes"]
        restored = Graph.from_dict(d)
        assert restored.entry == "start"
        assert len(restored.nodes) == 2
