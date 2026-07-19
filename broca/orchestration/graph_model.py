"""
Graph 数据模型

有向图编排的核心数据类型：Node、NodeType、Edge、Router、Graph、GraphBuilder。
不依赖任何编排器逻辑，可被 graph_orchestrator 和 pipeline 等模块引用。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import CrewConfig

logger = get_logger(__name__)


class NodeType(str, Enum):
    """节点类型"""

    TASK = "task"
    HUMAN = "human"
    CREW = "crew"


@dataclass
class Edge:
    """有向边"""

    target: str
    description: str = ""
    field: Optional[str] = None
    operator: str = "eq"
    value: Any = None
    context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"target": self.target}
        if self.description:
            result["description"] = self.description
        if self.field is not None:
            result["field"] = self.field
            result["operator"] = self.operator
            result["value"] = self.value
        if self.context:
            result["context"] = self.context
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Edge":
        return cls(
            target=data["target"],
            description=data.get("description", ""),
            field=data.get("field"),
            operator=data.get("operator", "eq"),
            value=data.get("value"),
            context=data.get("context"),
        )


@dataclass
class Router:
    """出边选择策略"""

    mode: Literal["static", "agent", "static_then_agent"]
    evaluator: Optional[str] = None
    prompt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"mode": self.mode}
        if self.evaluator:
            result["evaluator"] = self.evaluator
        if self.prompt:
            result["prompt"] = self.prompt
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Router":
        return cls(
            mode=data["mode"],
            evaluator=data.get("evaluator"),
            prompt=data.get("prompt"),
        )


@dataclass
class Node:
    """图节点"""

    name: str
    type: NodeType = NodeType.TASK
    # task 字段
    agent: Optional[str] = None
    task: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    # crew 字段
    crew_ref: Optional[str] = None
    # human 字段
    question: Optional[str] = None
    response_field: Optional[str] = None
    timeout: Optional[int] = None
    # 出边
    edges: List[Edge] = field(default_factory=list)
    # 路由器
    router: Optional[Router] = None
    # 循环控制
    max_loop: int = 0
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "name": self.name,
            "type": self.type.value,
        }
        if self.type == NodeType.TASK:
            if self.agent:
                result["agent"] = self.agent
            if self.task:
                result["task"] = self.task
            if self.context:
                result["context"] = self.context
        elif self.type == NodeType.HUMAN:
            if self.question:
                result["question"] = self.question
            if self.response_field:
                result["response_field"] = self.response_field
            if self.timeout is not None:
                result["timeout"] = self.timeout
            if self.context:
                result["context"] = self.context
        elif self.type == NodeType.CREW:
            if self.crew_ref:
                result["crew_ref"] = self.crew_ref
            if self.context:
                result["context"] = self.context
        if self.edges:
            result["edges"] = [e.to_dict() for e in self.edges]
        if self.router:
            result["router"] = self.router.to_dict()
        if self.max_loop:
            result["max_loop"] = self.max_loop
        if self.extras:
            result["extras"] = self.extras
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Node":
        node_type = NodeType(data.get("type", "task"))
        edges = [Edge.from_dict(e) for e in data.get("edges", [])]
        router = Router.from_dict(data["router"]) if "router" in data else None

        return cls(
            name=data["name"],
            type=node_type,
            agent=data.get("agent"),
            task=data.get("task"),
            context=data.get("context"),
            crew_ref=data.get("crew_ref"),
            question=data.get("question"),
            response_field=data.get("response_field"),
            timeout=data.get("timeout"),
            edges=edges,
            router=router,
            max_loop=data.get("max_loop", 0),
            extras=data.get("extras", {}),
        )


@dataclass
class Graph:
    """有向图定义"""

    nodes: Dict[str, Node]
    entry: str = "start"

    def compile(self) -> List[str]:
        """
        校验图有效性，返回错误列表。空列表=有效。

        校验规则：
        1. 入口存在：start 节点必须存在
        2. 目标存在：所有 edge.target 都指向存在的节点
        3. 可达性：所有节点都从 start 可达（无孤立节点）
        4. Fan-out 汇聚：并行分支要么都无出边，要么都连到同一个节点
        5. Human 完整性：human 节点必须有 question 和 response_field
        6. Router 完整性：agent 模式必须有 evaluator
        7. 名称唯一性：无重复节点名（dict 键已保证唯一）
        8. 循环检测：按环推导 max_loop
        """
        errors = []

        # 1. 入口存在
        if self.entry not in self.nodes:
            errors.append(f"Entry node '{self.entry}' not found in graph")

        # 2. 目标存在
        for name, node in self.nodes.items():
            for edge in node.edges:
                if edge.target not in self.nodes:
                    errors.append(
                        f"Node '{name}' edge target '{edge.target}' not found in graph"
                    )

        if errors:
            return errors

        # 3. 可达性
        reachable = self._compute_reachable()
        unreachable = [n for n in self.nodes if n not in reachable]
        if unreachable:
            errors.append(f"Unreachable nodes from '{self.entry}': {unreachable}")

        # 4. Fan-out 汇聚约束
        for name, node in self.nodes.items():
            if len(node.edges) > 1 and node.router:
                fan_out_errors = self._check_fan_out_convergence(name)
                errors.extend(fan_out_errors)

        # 5. Human 完整性
        for name, node in self.nodes.items():
            if node.type == NodeType.HUMAN:
                if not node.question:
                    errors.append(f"Human node '{name}' missing 'question'")
                if not node.response_field:
                    errors.append(f"Human node '{name}' missing 'response_field'")

        # 6. Router 完整性
        for name, node in self.nodes.items():
            if node.router and node.router.mode == "agent":
                if not node.router.evaluator:
                    errors.append(
                        f"Router on node '{name}' in agent mode missing 'evaluator'"
                    )

        # 8. 循环检测
        cycles = self._find_cycles()
        for cycle in cycles:
            explicit = [(n, self.nodes[n].max_loop) for n in cycle if self.nodes[n].max_loop > 0]
            if explicit:
                effective = min(v for _, v in explicit)
                sources = [n for n, v in explicit]
                for name in cycle:
                    node = self.nodes[name]
                    if node.max_loop == 0:
                        node.max_loop = effective
                        logger.info(
                            f"Cycle: node '{name}' inherits max_loop={effective} from {sources}"
                        )
            else:
                for name in cycle:
                    errors.append(
                        f"Warning: Node '{name}' is part of a cycle but no node in the "
                        f"cycle has max_loop set. Please set max_loop on at least one node."
                    )

        return errors

    def _compute_reachable(self) -> set:
        reachable = set()
        queue = deque([self.entry])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            node = self.nodes.get(current)
            if node:
                for edge in node.edges:
                    if edge.target not in reachable:
                        queue.append(edge.target)
        return reachable

    def _find_cycles(self) -> List[set]:
        index_counter = [0]
        stack = []
        indices: Dict[str, int] = {}
        lowlink: Dict[str, int] = {}
        on_stack: Dict[str, bool] = {}
        cycles: List[set] = []

        def strongconnect(name: str):
            indices[name] = lowlink[name] = index_counter[0]
            index_counter[0] += 1
            stack.append(name)
            on_stack[name] = True
            node = self.nodes.get(name)
            if node:
                for edge in node.edges:
                    target = edge.target
                    if target not in indices:
                        strongconnect(target)
                        lowlink[name] = min(lowlink[name], lowlink[target])
                    elif on_stack.get(target):
                        lowlink[name] = min(lowlink[name], indices[target])
            if lowlink[name] == indices[name]:
                scc = set()
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    scc.add(w)
                    if w == name:
                        break
                if len(scc) > 1:
                    cycles.append(scc)
                elif len(scc) == 1:
                    node = self.nodes.get(name)
                    if node and any(e.target == name for e in node.edges):
                        cycles.append(scc)

        for name in self.nodes:
            if name not in indices:
                strongconnect(name)
        return cycles

    def _check_fan_out_convergence(self, router_node_name: str) -> List[str]:
        errors = []
        router_node = self.nodes[router_node_name]
        if not router_node.router:
            return []

        has_unconditional = any(e.field is None for e in router_node.edges)
        conditional_edges = [e for e in router_node.edges if e.field is not None]
        if has_unconditional and len(conditional_edges) <= 1:
            return []

        branch_terminals = {}
        for edge in router_node.edges:
            if edge.field is None:
                continue
            terminal = self._trace_to_terminal(edge.target, set())
            branch_terminals[edge.target] = terminal

        if len(branch_terminals) < 2:
            return []

        terminals_list = list(branch_terminals.values())
        has_successors = [t is not None for t in terminals_list]
        if not all(has_successors) and not all(not s for s in has_successors):
            branch_names = list(branch_terminals.keys())
            errors.append(
                f"Fan-out from '{router_node_name}': branches {branch_names} "
                f"have mixed successor states (some have successors, some don't)"
            )
            return errors

        terminal_nodes = [t for t in terminals_list if t is not None]
        if len(terminal_nodes) >= 2:
            if len(set(terminal_nodes)) > 1:
                branch_names = list(branch_terminals.keys())
                errors.append(
                    f"Fan-out from '{router_node_name}': branches {branch_names} "
                    f"diverge to different convergence nodes: {set(terminal_nodes)}. "
                    f"All branches must converge to the same node."
                )
        return errors

    def _trace_to_terminal(self, start: str, visited: set) -> Optional[str]:
        if start in visited or start not in self.nodes:
            return None
        visited.add(start)
        node = self.nodes[start]
        if not node.edges:
            return None
        if node.router and len(node.edges) > 1:
            return node.name
        return self._trace_to_terminal(node.edges[0].target, visited)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": {name: node.to_dict() for name, node in self.nodes.items()},
            "entry": self.entry,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Graph":
        nodes_data = data.get("nodes", {})
        nodes = {}
        for name, node_data in nodes_data.items():
            if "name" not in node_data:
                node_data = dict(node_data)
                node_data["name"] = name
            nodes[name] = Node.from_dict(node_data)
        return cls(nodes=nodes, entry=data.get("entry", "start"))


class GraphBuilder:
    """
    Graph 构建器

    从 YAML/字典解析图定义。
    格式要求：extras.graph.nodes / extras.graph.entry
    """

    @staticmethod
    def from_crew_config(config: CrewConfig) -> Optional["Graph"]:
        extras = config.orchestrator.extras
        graph_data = extras.get("graph")
        if graph_data:
            return Graph.from_dict(graph_data)
        return None
