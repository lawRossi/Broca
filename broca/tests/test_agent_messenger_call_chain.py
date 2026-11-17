"""Unit tests for :class:`CallChain` — the cycle-detection primitive.

``CallChain`` is a value object that tracks the chain of agents a message has
traversed.  It is used by ``DefaultAgentMessenger`` for *request* forced cycle
detection (deadlock prevention).  These tests pin down its pure logic only.

No ``CommunicationBudget`` tests exist (optional enhancement skipped per user
request — there is no ``budget.py``).
"""

from __future__ import annotations

from broca.agent_messenger.call_chain import CallChain


class TestWouldCreateCycle:
    def test_empty_chain_never_cycles(self):
        chain = CallChain()
        assert chain.would_create_cycle("A") is False
        assert chain.would_create_cycle("") is False

    def test_single_node_chain_cycles_on_itself(self):
        chain = CallChain(agent_ids=["A"])
        assert chain.would_create_cycle("A") is True

    def test_single_node_chain_does_not_cycle_on_other(self):
        chain = CallChain(agent_ids=["A"])
        assert chain.would_create_cycle("B") is False

    def test_multi_node_chain_cycles_on_any_member(self):
        chain = CallChain(agent_ids=["A", "B", "C"])
        assert chain.would_create_cycle("A") is True
        assert chain.would_create_cycle("B") is True
        assert chain.would_create_cycle("C") is True

    def test_multi_node_chain_does_not_cycle_on_new(self):
        chain = CallChain(agent_ids=["A", "B"])
        assert chain.would_create_cycle("Z") is False


class TestIsWithinDepth:
    def test_empty_chain_within_depth(self):
        assert CallChain().is_within_depth(3) is True

    def test_depth_less_than_max_is_within(self):
        chain = CallChain(agent_ids=["A", "B"])
        assert chain.is_within_depth(3) is True  # depth 2 < 3

    def test_depth_equal_to_max_is_not_within(self):
        chain = CallChain(agent_ids=["A", "B", "C"])
        assert chain.is_within_depth(3) is False  # depth 3 == 3

    def test_depth_greater_than_max_is_not_within(self):
        chain = CallChain(agent_ids=["A", "B", "C", "D"])
        assert chain.is_within_depth(3) is False


class TestAddImmutability:
    def test_add_returns_new_instance(self):
        chain = CallChain(agent_ids=["A"])
        extended = chain.add("B")
        assert extended is not chain

    def test_add_does_not_mutate_original(self):
        chain = CallChain(agent_ids=["A"])
        chain.add("B")
        assert chain.agent_ids == ["A"]

    def test_add_appends_in_order(self):
        chain = CallChain(agent_ids=["A"]).add("B").add("C")
        assert chain.agent_ids == ["A", "B", "C"]

    def test_add_on_empty(self):
        assert CallChain().add("A").agent_ids == ["A"]


class TestDepth:
    def test_depth_empty(self):
        assert CallChain().depth == 0

    def test_depth_counts_nodes(self):
        assert CallChain(agent_ids=["A", "B", "C"]).depth == 3


class TestSerialization:
    def test_to_dict(self):
        chain = CallChain(agent_ids=["A", "B"])
        assert chain.to_dict() == {"agent_ids": ["A", "B"]}

    def test_to_dict_is_a_copy(self):
        chain = CallChain(agent_ids=["A"])
        data = chain.to_dict()
        data["agent_ids"].append("B")
        assert chain.agent_ids == ["A"]

    def test_round_trip(self):
        chain = CallChain(agent_ids=["A", "B", "C"])
        restored = CallChain.from_dict(chain.to_dict())
        assert restored.agent_ids == chain.agent_ids
        assert restored.depth == chain.depth

    def test_from_dict_none_returns_empty(self):
        assert CallChain.from_dict(None).agent_ids == []

    def test_from_dict_empty_dict_returns_empty(self):
        assert CallChain.from_dict({}).agent_ids == []


class TestDescribe:
    def test_describe_empty(self):
        assert CallChain().describe() == "(empty)"

    def test_describe_joins_with_arrow(self):
        assert CallChain(agent_ids=["A", "B"]).describe() == "A → B"
