"""
Error Handler Module

This module provides unified error handling for agent operations, including:
- Standardized error types and handling
- Error logging and reporting
- Error recovery strategies
- Context-aware error handling
"""

import asyncio
import traceback
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Callable, Dict, Optional

from loguru import logger

from broca.session import MessageRole, MessageType, SessionManager


class ErrorType(str, Enum):
    """Error type enumeration"""

    LLM_ERROR = "llm_error"
    TOOL_ERROR = "tool_error"
    PERMISSION_ERROR = "permission_error"
    COMMUNICATION_ERROR = "communication_error"
    EXECUTION_ERROR = "execution_error"
    TIMEOUT_ERROR = "timeout_error"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN_ERROR = "unknown_error"


class AgentError(Exception):
    """Base exception for agent-related errors"""

    def __init__(
        self,
        error_type: ErrorType,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        self.error_type = error_type
        self.message = message
        self.details = details or {}
        self.original_error = original_error
        super().__init__(message)

    def __str__(self) -> str:
        return f"{self.error_type}: {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary"""
        return {
            "error_type": self.error_type,
            "message": self.message,
            "details": self.details,
            "original_error": str(self.original_error) if self.original_error else None,
            "traceback": traceback.format_exc() if self.original_error else None,
        }


class ErrorHandler:
    """
    Unified error handler for agent operations

    Provides consistent error handling across different modules
    """

    def __init__(
        self,
        session_manager: Optional[SessionManager] = None,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        """
        Initialize error handler

        Args:
            session_manager: Optional session manager for error logging
            turn_id: Optional turn ID for error context
            agent_id: Optional agent ID for error context
        """
        self.session_manager = session_manager
        self.turn_id = turn_id
        self.agent_id = agent_id

    def set_context(
        self,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_manager: Optional[SessionManager] = None,
    ):
        """
        Set error handler context

        Args:
            turn_id: Turn ID for error context
            agent_id: Agent ID for error context
            session_manager: Session manager for error logging
        """
        self.turn_id = turn_id
        self.agent_id = agent_id
        if session_manager:
            self.session_manager = session_manager

    @asynccontextmanager
    async def handle_llm_call(self, context: str = "llm_call"):
        """
        Context manager for handling LLM call errors

        Args:
            context: Context description for error logging
        """
        try:
            yield
        except asyncio.TimeoutError as e:
            await self._handle_timeout_error(
                ErrorType.LLM_ERROR,
                f"LLM call timed out: {context}",
                {"context": context},
                e,
            )
            raise AgentError(
                ErrorType.TIMEOUT_ERROR,
                f"LLM call timed out: {context}",
                {"context": context},
                e,
            )
        except Exception as e:
            await self._handle_generic_error(
                ErrorType.LLM_ERROR,
                f"LLM call failed: {context}",
                {"context": context},
                e,
            )
            raise AgentError(
                ErrorType.LLM_ERROR,
                f"LLM call failed: {context}",
                {"context": context},
                e,
            )

    @asynccontextmanager
    async def handle_tool_execution(
        self, tool_name: str, context: str = "tool_execution"
    ):
        """
        Context manager for handling tool execution errors

        Args:
            tool_name: Name of the tool being executed
            context: Context description for error logging
        """
        try:
            yield
        except asyncio.TimeoutError as e:
            await self._handle_timeout_error(
                ErrorType.TOOL_ERROR,
                f"Tool execution timed out: {tool_name}",
                {"tool_name": tool_name, "context": context},
                e,
            )
            raise AgentError(
                ErrorType.TIMEOUT_ERROR,
                f"Tool execution timed out: {tool_name}",
                {"tool_name": tool_name, "context": context},
                e,
            )
        except Exception as e:
            await self._handle_generic_error(
                ErrorType.TOOL_ERROR,
                f"Tool execution failed: {tool_name}",
                {"tool_name": tool_name, "context": context},
                e,
            )
            raise AgentError(
                ErrorType.TOOL_ERROR,
                f"Tool execution failed: {tool_name}",
                {"tool_name": tool_name, "context": context},
                e,
            )

    @asynccontextmanager
    async def handle_permission_request(self, request_id: Optional[str] = None):
        """
        Context manager for handling permission request errors

        Args:
            request_id: Optional permission request ID
        """
        try:
            yield
        except asyncio.TimeoutError as e:
            await self._handle_timeout_error(
                ErrorType.PERMISSION_ERROR,
                "Permission request timed out",
                {"request_id": request_id},
                e,
            )
            raise AgentError(
                ErrorType.TIMEOUT_ERROR,
                "Permission request timed out",
                {"request_id": request_id},
                e,
            )
        except Exception as e:
            await self._handle_generic_error(
                ErrorType.PERMISSION_ERROR,
                "Permission request failed",
                {"request_id": request_id},
                e,
            )
            raise AgentError(
                ErrorType.PERMISSION_ERROR,
                "Permission request failed",
                {"request_id": request_id},
                e,
            )

    @asynccontextmanager
    async def handle_communication(self, operation: str):
        """
        Context manager for handling communication errors

        Args:
            operation: Communication operation description
        """
        try:
            yield
        except Exception as e:
            await self._handle_generic_error(
                ErrorType.COMMUNICATION_ERROR,
                f"Communication failed: {operation}",
                {"operation": operation},
                e,
            )
            raise AgentError(
                ErrorType.COMMUNICATION_ERROR,
                f"Communication failed: {operation}",
                {"operation": operation},
                e,
            )

    @asynccontextmanager
    async def handle_execution_step(self, step_number: Optional[int] = None):
        """
        Context manager for handling execution step errors

        Args:
            step_number: Optional step number for context
        """
        try:
            yield
        except Exception as e:
            await self._handle_generic_error(
                ErrorType.EXECUTION_ERROR,
                "Execution step failed",
                {"step_number": step_number},
                e,
            )
            raise AgentError(
                ErrorType.EXECUTION_ERROR,
                "Execution step failed",
                {"step_number": step_number},
                e,
            )

    async def _handle_timeout_error(
        self,
        error_type: ErrorType,
        message: str,
        details: Dict[str, Any],
        original_error: Exception,
    ):
        """Handle timeout errors"""
        logger.error(f"{error_type}: {message}")

        # Log to database if session manager is available
        await self._log_error_to_database(error_type, message, details, original_error)

    async def _handle_generic_error(
        self,
        error_type: ErrorType,
        message: str,
        details: Dict[str, Any],
        original_error: Exception,
    ):
        """Handle generic errors"""
        logger.error(f"{error_type}: {message}")
        logger.error(traceback.format_exc())

        # Log to database if session manager is available
        await self._log_error_to_database(error_type, message, details, original_error)

    async def _log_error_to_database(
        self,
        error_type: ErrorType,
        message: str,
        details: Dict[str, Any],
        original_error: Exception,
    ):
        """
        Log error to database

        Args:
            error_type: Type of error
            message: Error message
            details: Error details
            original_error: Original exception
        """
        if self.session_manager and self.turn_id:
            try:
                error_data = {
                    "error_type": error_type,
                    "message": message,
                    "details": details,
                    "original_error": str(original_error),
                    "traceback": traceback.format_exc(),
                }

                await self.session_manager.save_message(
                    role=MessageRole.SYSTEM,
                    content=message,
                    message_type=MessageType.ERROR,
                    turn_id=self.turn_id,
                    agent_id=self.agent_id,
                    data=error_data,
                )
            except Exception as save_error:
                logger.error(f"Failed to save error to database: {save_error}")

    def wrap_async_function(
        self,
        func: Callable,
        error_type: ErrorType,
        context: str = "function_execution",
    ) -> Callable:
        """
        Wrap an async function with error handling

        Args:
            func: Async function to wrap
            error_type: Type of error to catch
            context: Context description for error logging

        Returns:
            Wrapped async function
        """

        async def wrapped(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                await self._handle_generic_error(
                    error_type,
                    f"{context} failed",
                    {"function": func.__name__, "context": context},
                    e,
                )
                raise AgentError(
                    error_type,
                    f"{context} failed",
                    {"function": func.__name__, "context": context},
                    e,
                )

        return wrapped

    def create_error_decorator(
        self,
        error_type: ErrorType,
        context: str = "function_execution",
    ):
        """
        Create a decorator for error handling

        Args:
            error_type: Type of error to catch
            context: Context description for error logging

        Returns:
            Error handling decorator
        """

        def decorator(func):
            return self.wrap_async_function(func, error_type, context)

        return decorator
