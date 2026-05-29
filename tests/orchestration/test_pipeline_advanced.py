"""
Pipeline 增强版测试

测试 fan-out / fan-in / condition / switch 四种新步骤类型。
"""

import pytest
from broca.orchestration.pipeline import (
    PipelineStep,
    PipelineStepType,
    BranchDefinition,
    _evaluate_condition,
    _match_switch,
)


class TestPipelineStep:
    """PipelineStep 序列化/反序列化测试"""

    def test_task_step_roundtrip(self):
        """普通 TASK 步骤序列化往返"""
        d = {"agent": "reviewer", "task": "review code", "context": "be thorough"}
        s = PipelineStep.from_dict(d)
        assert s.type == PipelineStepType.TASK
        assert s.agent == "reviewer"
        assert s.task == "review code"
        assert s.context == "be thorough"

        d2 = s.to_dict()
        assert d2["type"] == "task"
        assert d2["agent"] == "reviewer"

    def test_task_step_no_type_backward_compat(self):
        """无 type 字段兼容旧格式"""
        d = {"agent": "a1", "task": "do work"}
        s = PipelineStep.from_dict(d)
        assert s.type == PipelineStepType.TASK

    def test_fan_out_step(self):
        """FAN-OUT 步骤解析"""
        d = {
            "type": "fan-out",
            "name": "并行分析",
            "branches": [
                {"name": "分支A", "agent": "agent_a", "task": "task A"},
                {"name": "分支B", "agent": "agent_b", "task": "task B"},
            ],
        }
        s = PipelineStep.from_dict(d)
        assert s.type == PipelineStepType.FAN_OUT
        assert s.name == "并行分析"
        assert len(s.branches) == 2
        assert s.branches[0].name == "分支A"
        assert s.branches[1].agent == "agent_b"

        d2 = s.to_dict()
        assert d2["type"] == "fan-out"
        assert len(d2["branches"]) == 2

    def test_fan_in_step_concat(self):
        """FAN-IN 步骤（concat 策略）"""
        d = {
            "type": "fan-in",
            "name": "汇聚",
            "aggregation_strategy": "concat",
            "sources": ["分支A", "分支B"],
        }
        s = PipelineStep.from_dict(d)
        assert s.type == PipelineStepType.FAN_IN
        assert s.aggregation_strategy == "concat"
        assert s.sources == ["分支A", "分支B"]

    def test_fan_in_step_agent(self):
        """FAN-IN 步骤（agent 策略）"""
        d = {
            "type": "fan-in",
            "aggregation_strategy": "agent",
            "aggregator": "质量管理员",
            "sources": ["安全审计", "性能分析"],
            "task": "综合以上结果",
        }
        s = PipelineStep.from_dict(d)
        assert s.type == PipelineStepType.FAN_IN
        assert s.aggregator == "质量管理员"
        assert s.aggregation_strategy == "agent"

    def test_condition_step(self):
        """CONDITION 步骤"""
        d = {
            "type": "condition",
            "name": "质量检查",
            "condition_field": "pipeline.step_1.score",
            "condition_operator": "gte",
            "condition_value": 0.7,
            "branches": [
                {"name": "通过", "agent": "deploy", "task": "批准"},
                {"name": "不通过", "agent": "notify", "task": "拒绝"},
            ],
            "default_branch": "不通过",
        }
        s = PipelineStep.from_dict(d)
        assert s.type == PipelineStepType.CONDITION
        assert s.condition_field == "pipeline.step_1.score"
        assert s.condition_operator == "gte"
        assert s.condition_value == 0.7
        assert s.default_branch == "不通过"
        assert len(s.branches) == 2

    def test_switch_step(self):
        """SWITCH 步骤"""
        d = {
            "type": "switch",
            "name": "分类处理",
            "switch_field": "pipeline.step_1.category",
            "branches": [
                {"name": "紧急", "agent": "u", "task": "urgent"},
                {"name": "普通", "agent": "n", "task": "normal"},
            ],
            "default_branch": "普通",
        }
        s = PipelineStep.from_dict(d)
        assert s.type == PipelineStepType.SWITCH
        assert s.switch_field == "pipeline.step_1.category"
        assert s.default_branch == "普通"

    def test_unknown_type_raises(self):
        """未知类型抛出异常"""
        with pytest.raises(ValueError):
            PipelineStep.from_dict({"type": "unknown"})


class TestConditionEvaluation:
    """条件表达式求值测试"""

    @pytest.mark.parametrize(
        "actual, operator, target, expected",
        [
            (0.85, "gte", 0.7, True),
            (0.5, "gte", 0.7, False),
            (0.7, "gte", 0.7, True),
            (0.7, "gt", 0.7, False),
            (0.8, "gt", 0.7, True),
            (0.5, "lt", 0.7, True),
            (0.5, "lte", 0.7, True),
            (0.7, "lte", 0.7, True),
            (42, "eq", 42, True),
            (42, "eq", 43, False),
            (42, "ne", 43, True),
            ("hello", "contains", "ell", True),
            ("hello", "contains", "xyz", False),
            ("hello", "startswith", "he", True),
            ("hello", "startswith", "lo", False),
            ("hello", "endswith", "lo", True),
            ("hello", "endswith", "he", False),
            (None, "eq", None, True),
            ("", "eq", "", True),
        ],
    )
    def test_operator(self, actual, operator, target, expected):
        assert _evaluate_condition(actual, operator, target) == expected

    def test_unknown_operator_fallback(self):
        """未知运算符回退到 eq"""
        assert _evaluate_condition(42, "unknown_op", 42) is True
        assert _evaluate_condition(42, "unknown_op", 43) is False


class TestSwitchMatching:
    """Switch 分支匹配测试"""

    def setup_method(self):
        self.branches = [
            BranchDefinition(name="紧急", agent="a1", task="t1"),
            BranchDefinition(name="普通", agent="a2", task="t2"),
            BranchDefinition(name="低优先级", agent="a3", task="t3"),
        ]

    def test_exact_match(self):
        assert _match_switch("紧急", self.branches) == "紧急"
        assert _match_switch("普通", self.branches) == "普通"

    def test_default_fallback(self):
        assert _match_switch("不存在的", self.branches, "普通") == "普通"

    def test_no_match_no_default(self):
        assert _match_switch("不存在的", self.branches) is None

    def test_none_value(self):
        assert _match_switch(None, self.branches, "普通") == "普通"
        assert _match_switch(None, self.branches) is None


class TestStepToDictFromDictRoundtrip:
    """各种步骤类型的 to_dict/from_dict 往返测试"""

    @pytest.mark.parametrize(
        "input_dict",
        [
            {"agent": "a", "task": "t"},
            {"agent": "a", "task": "t", "context": "ctx"},
            {"type": "task", "agent": "a", "task": "t"},
            {
                "type": "fan-out",
                "name": "fo",
                "branches": [
                    {"name": "b1", "agent": "a1", "task": "t1"},
                    {"name": "b2", "agent": "a2", "task": "t2"},
                ],
            },
            {
                "type": "fan-in",
                "name": "fi",
                "aggregation_strategy": "concat",
                "sources": ["b1", "b2"],
            },
            {
                "type": "condition",
                "name": "cond",
                "condition_field": "score",
                "condition_operator": "gte",
                "condition_value": 0.7,
                "branches": [
                    {"name": "yes", "agent": "a1", "task": "t1"},
                    {"name": "no", "agent": "a2", "task": "t2"},
                ],
                "default_branch": "no",
            },
            {
                "type": "switch",
                "name": "sw",
                "switch_field": "cat",
                "branches": [
                    {"name": "a", "agent": "a1", "task": "t1"},
                ],
                "default_branch": "a",
            },
        ],
    )
    def test_roundtrip(self, input_dict):
        s = PipelineStep.from_dict(input_dict)
        d = s.to_dict()
        s2 = PipelineStep.from_dict(d)
        assert s.type == s2.type
        assert s.to_dict()["type"] == d["type"]
