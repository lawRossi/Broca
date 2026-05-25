"""
错误恢复与 Human-in-the-loop 模块

提供编排执行中的错误处理、重试策略、死循环检测和人工审批节点。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from broca.logging_config import get_logger

logger = get_logger(__name__)


class RetryStrategy(str, Enum):
    """重试策略"""

    FIXED = "fixed"          # 固定间隔重试
    EXPONENTIAL = "exponential"  # 指数退避
    IMMEDIATE = "immediate"  # 立即重试


@dataclass
class RetryConfig:
    """重试配置"""

    max_retries: int = 3
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    base_delay: float = 1.0  # 秒
    max_delay: float = 60.0  # 秒


@dataclass
class CircuitBreakerConfig:
    """断路器配置"""

    failure_threshold: int = 5       # 连续失败次数阈值
    recovery_timeout: float = 30.0   # 恢复超时（秒）
    half_open_max_requests: int = 1  # 半开状态最大请求数


class CircuitState(str, Enum):
    """断路器状态"""

    CLOSED = "closed"          # 正常
    OPEN = "open"              # 断开
    HALF_OPEN = "half_open"    # 半开


class CircuitBreaker:
    """
    断路器

    防止重复调用失败的 Agent 或操作。
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.half_open_requests = 0

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过断路器调用函数

        如果断路器已断开，直接抛出异常。
        """
        if self.state == CircuitState.OPEN:
            if self._should_recover():
                self.state = CircuitState.HALF_OPEN
                self.half_open_requests = 0
            else:
                raise CircuitBreakerOpenError("Circuit breaker is OPEN")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _should_recover(self) -> bool:
        """检查是否应该尝试恢复"""
        if not self.last_failure_time:
            return True
        elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
        return elapsed >= self.config.recovery_timeout

    def _on_success(self) -> None:
        """成功调用后的处理"""
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_requests += 1
            if self.half_open_requests >= self.config.half_open_max_requests:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
        else:
            self.failure_count = 0

    def _on_failure(self) -> None:
        """失败调用后的处理"""
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)

        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures"
            )

    def reset(self) -> None:
        """重置断路器"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_requests = 0


class CircuitBreakerOpenError(Exception):
    """断路器断开异常"""
    pass


class RetryHandler:
    """
    重试处理器

    支持固定间隔、指数退避和立即重试三种策略。
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()

    async def execute(
        self,
        func: Callable,
        *args,
        context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        """
        带重试的执行

        Args:
            func: 要执行的异步函数
            context: 执行上下文（用于日志）

        Returns:
            函数执行结果

        Raises:
            Last attempt 的异常
        """
        last_exception = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                ctx_str = f" (context: {context})" if context else ""

                if attempt < self.config.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        f"Attempt {attempt}/{self.config.max_retries} failed: {e}{ctx_str}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"All {self.config.max_retries} attempts failed: {e}{ctx_str}"
                    )

        raise last_exception

    def _calculate_delay(self, attempt: int) -> float:
        """计算重试延迟"""
        if self.config.strategy == RetryStrategy.IMMEDIATE:
            return 0
        elif self.config.strategy == RetryStrategy.FIXED:
            return self.config.base_delay
        elif self.config.strategy == RetryStrategy.EXPONENTIAL:
            delay = self.config.base_delay * (2 ** (attempt - 1))
            return min(delay, self.config.max_delay)
        return self.config.base_delay


class DeadLoopDetector:
    """
    死循环检测器

    检测编排中 Agent 是否陷入重复无意义的循环。
    """

    def __init__(self, max_similar_responses: int = 3, similarity_threshold: float = 0.9):
        self.max_similar_responses = max_similar_responses
        self.similarity_threshold = similarity_threshold
        self._response_history: Dict[str, List[str]] = {}

    def check(self, agent_name: str, response: str) -> bool:
        """
        检查 Agent 是否陷入死循环

        Args:
            agent_name: Agent 名称
            response: 当前响应内容

        Returns:
            True 如果检测到死循环
        """
        if agent_name not in self._response_history:
            self._response_history[agent_name] = []

        history = self._response_history[agent_name]
        history.append(response)

        # 只保留最近 N 条
        if len(history) > self.max_similar_responses:
            history.pop(0)

        # 检查是否有足够的记录
        if len(history) < self.max_similar_responses:
            return False

        # 检查所有记录是否相似
        if all(
            self._is_similar(history[0], h) for h in history[1:]
        ):
            logger.warning(
                f"Dead loop detected for agent '{agent_name}': "
                f"{self.max_similar_responses} similar responses"
            )
            return True

        return False

    def _is_similar(self, a: str, b: str) -> bool:
        """简单的文本相似度检查"""
        if not a or not b:
            return False

        # 使用最长公共子序列的比例作为相似度
        min_len = min(len(a), len(b))
        if min_len == 0:
            return False

        # 简单的 Jaccard 相似度（基于词）
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return False

        intersection = words_a & words_b
        union = words_a | words_b
        similarity = len(intersection) / len(union)

        return similarity >= self.similarity_threshold

    def reset(self, agent_name: Optional[str] = None) -> None:
        """重置历史记录"""
        if agent_name:
            self._response_history.pop(agent_name, None)
        else:
            self._response_history.clear()


class HumanInTheLoop:
    """
    Human-in-the-loop 审批节点

    在编排的关键决策点插入人类审批步骤。
    Agent 在审批节点暂停执行，等待用户确认后再继续。
    """

    def __init__(self, agent_ask_func: Optional[Callable] = None):
        """
        Args:
            agent_ask_func: 用于向用户提问的函数
                          默认使用 ask_user 工具
        """
        self._ask_func = agent_ask_func

    async def request_approval(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 300.0,
    ) -> ApprovalResult:
        """
        请求用户审批

        Args:
            question: 向用户展示的问题
            context: 附加上下文信息
            timeout: 等待超时（秒）

        Returns:
            ApprovalResult 审批结果
        """
        prompt = question
        if context:
            context_str = "\n".join(
                f"  {k}: {v}" for k, v in context.items()
            )
            prompt = f"{question}\n\nContext:\n{context_str}"

        prompt += "\n\nPlease approve or reject with a reason."

        try:
            if self._ask_func:
                answer = await self._ask_func(prompt)
            else:
                # 使用默认的 ask_user
                from broca.tools.agent_interaction import AskUserToolManager

                answer = await self._ask_via_ask_user(prompt, timeout)

            return self._parse_approval(answer)

        except asyncio.TimeoutError:
            return ApprovalResult(
                approved=False,
                reason="Timeout waiting for user response",
                timeout=True,
            )
        except Exception as e:
            logger.error(f"Approval request failed: {e}")
            return ApprovalResult(
                approved=False,
                reason=f"Error: {e}",
            )

    async def _ask_via_ask_user(self, question: str, timeout: float) -> str:
        """通过 ask_user 工具提问"""
        from broca.tools.agent_interaction import AskUser

        tool = AskUser()
        from broca.tools.tool import ToolCallContext

        ctx = ToolCallContext()
        result = await tool._execute(
            {"question": question, "options": [
                {"name": "approve", "description": "Approve and continue"},
                {"name": "reject", "description": "Reject and provide feedback"},
            ]},
            ctx,
        )
        return result.content

    def _parse_approval(self, answer: str) -> "ApprovalResult":
        """解析用户的审批回复"""
        answer_lower = answer.lower().strip()

        # 检查关键词
        if any(word in answer_lower for word in ["approve", "yes", "同意", "批准", "继续"]):
            return ApprovalResult(
                approved=True,
                reason=answer,
            )
        elif any(word in answer_lower for word in ["reject", "no", "拒绝", "不同意", "停止"]):
            return ApprovalResult(
                approved=False,
                reason=answer,
            )
        else:
            # 无法明确判断，默认为拒绝
            return ApprovalResult(
                approved=False,
                reason=f"Unclear response: {answer}",
            )


@dataclass
class ApprovalResult:
    """审批结果"""

    approved: bool
    reason: str = ""
    timeout: bool = False
    feedback: Optional[str] = None


class ErrorRecoveryManager:
    """
    错误恢复管理器

    整合断路器、重试处理器、死循环检测器，提供统一的错误恢复能力。
    """

    def __init__(
        self,
        retry_config: Optional[RetryConfig] = None,
        circuit_config: Optional[CircuitBreakerConfig] = None,
        dead_loop_config: Optional[Dict[str, Any]] = None,
    ):
        self.retry_handler = RetryHandler(retry_config)
        self.circuit_breaker = CircuitBreaker(circuit_config)
        self.dead_loop_detector = DeadLoopDetector(
            **(dead_loop_config or {})
        )
        self.human_in_the_loop = HumanInTheLoop()

    async def safe_execute(
        self,
        func: Callable,
        *args,
        agent_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        require_approval: bool = False,
        approval_question: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """
        安全的编排执行（含重试 + 断路器 + 死循环检测 + HITL）

        Args:
            func: 要执行的异步函数
            agent_name: Agent 名称（用于死循环检测）
            context: 执行上下文
            require_approval: 是否需要人工审批
            approval_question: 审批问题

        Returns:
            执行结果

        Raises:
            CircuitBreakerOpenError: 断路器断开
            RuntimeError: 所有重试均失败
        """
        # 1. 断路器检查
        try:
            result = await self.circuit_breaker.call(
                self.retry_handler.execute,
                func, *args,
                context=context,
                **kwargs,
            )
        except CircuitBreakerOpenError:
            raise
        except Exception as e:
            raise RuntimeError(f"Execution failed after all retries: {e}") from e

        # 2. 死循环检测
        if agent_name and isinstance(result, str):
            if self.dead_loop_detector.check(agent_name, result):
                logger.warning(
                    f"Dead loop detected for '{agent_name}'. "
                    f"Asking user for guidance."
                )
                approval = await self.human_in_the_loop.request_approval(
                    f"Agent '{agent_name}' appears to be in a loop. "
                    f"Last response: {result[:200]}...\n"
                    f"Should we continue or abort?",
                )
                if not approval.approved:
                    raise RuntimeError(
                        f"Dead loop confirmed by user for '{agent_name}': {approval.reason}"
                    )
                # 用户批准继续，重置检测器
                self.dead_loop_detector.reset(agent_name)

        # 3. 人工审批节点
        if require_approval:
            approval = await self.human_in_the_loop.request_approval(
                approval_question or "Do you approve proceeding with this step?",
                context=context,
            )
            if not approval.approved:
                raise RuntimeError(
                    f"Step rejected by user: {approval.reason}"
                )

        return result
