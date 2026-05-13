"""
Human-in-the-loop interrupt handling for workflows.

Provides mechanisms for pausing workflow execution,
waiting for human input, and resuming with user decisions.

Usage:
    from app.rag.core.interrupt import (
        InterruptHandler,
        PendingInterrupt,
        require_approval,
    )

    @task
    def review_node(state: Dict) -> Union[Command, Interrupt]:
        if needs_review(state):
            return require_approval(
                state["answer"],
                "Please review this answer",
            )
        return Command(goto="finish")
"""


import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.rag.core.command import Command, Interrupt, interrupt
from app.rag.core.logging import get_logger

logger = get_logger("rag.core.interrupt")

# Configuration
HUMAN_REVIEW_ENABLED = getattr(settings, "HUMAN_REVIEW_ENABLED", False)
INTERRUPT_TIMEOUT_SEC = getattr(settings, "INTERRUPT_TIMEOUT_SEC", 3600)  # 1 hour


class InterruptStatus(str, Enum):
    """Status of a pending interrupt."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class PendingInterrupt:
    """
    Represents a pending interrupt waiting for human input.

    Stored in the interrupt registry until resolved.
    """
    id: str
    session_id: str
    thread_id: str
    checkpoint_id: str | None
    interrupt: Interrupt
    status: InterruptStatus = InterruptStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    response: Any | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None

    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(seconds=INTERRUPT_TIMEOUT_SEC)

    def is_expired(self) -> bool:
        """Check if the interrupt has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC).replace(tzinfo=None) > self.expires_at

    def is_pending(self) -> bool:
        """Check if still waiting for response."""
        return self.status == InterruptStatus.PENDING and not self.is_expired()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "checkpoint_id": self.checkpoint_id,
            "status": self.status.value,
            "prompt": self.interrupt.prompt,
            "options": self.interrupt.options,
            "value": self.interrupt.value,
            "metadata": self.interrupt.metadata,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "response": self.response,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
        }


class InterruptRegistry:
    """
    Registry for pending interrupts.

    Stores and manages pending interrupts awaiting human resolution.
    Thread-safe for concurrent access.
    """

    def __init__(self):
        self._pending: dict[str, PendingInterrupt] = {}
        self._by_session: dict[str, list[str]] = {}
        self._by_thread: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        interrupt_obj: Interrupt,
        session_id: str,
        thread_id: str,
        checkpoint_id: str | None = None,
    ) -> PendingInterrupt:
        """
        Register a new pending interrupt.

        Args:
            interrupt_obj: The interrupt to register
            session_id: User/conversation session ID
            thread_id: Workflow thread ID
            checkpoint_id: Optional checkpoint ID for resumption

        Returns:
            PendingInterrupt object
        """
        async with self._lock:
            interrupt_id = str(uuid4())
            pending = PendingInterrupt(
                id=interrupt_id,
                session_id=session_id,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                interrupt=interrupt_obj,
            )

            self._pending[interrupt_id] = pending

            if session_id not in self._by_session:
                self._by_session[session_id] = []
            self._by_session[session_id].append(interrupt_id)

            if thread_id not in self._by_thread:
                self._by_thread[thread_id] = []
            self._by_thread[thread_id].append(interrupt_id)

            logger.info(
                "Registered interrupt %s for session %s, thread %s",
                interrupt_id, session_id, thread_id
            )
            return pending

    async def get(self, interrupt_id: str) -> PendingInterrupt | None:
        """Get a pending interrupt by ID."""
        async with self._lock:
            pending = self._pending.get(interrupt_id)
            if pending and pending.is_expired():
                pending.status = InterruptStatus.TIMEOUT
            return pending

    async def get_by_session(self, session_id: str) -> list[PendingInterrupt]:
        """Get all pending interrupts for a session."""
        async with self._lock:
            interrupt_ids = self._by_session.get(session_id, [])
            result = []
            for iid in interrupt_ids:
                pending = self._pending.get(iid)
                if pending:
                    if pending.is_expired():
                        pending.status = InterruptStatus.TIMEOUT
                    if pending.is_pending():
                        result.append(pending)
            return result

    async def get_by_thread(self, thread_id: str) -> list[PendingInterrupt]:
        """Get all pending interrupts for a thread."""
        async with self._lock:
            interrupt_ids = self._by_thread.get(thread_id, [])
            result = []
            for iid in interrupt_ids:
                pending = self._pending.get(iid)
                if pending:
                    if pending.is_expired():
                        pending.status = InterruptStatus.TIMEOUT
                    if pending.is_pending():
                        result.append(pending)
            return result

    async def resolve(
        self,
        interrupt_id: str,
        status: InterruptStatus,
        response: Any = None,
        resolved_by: str | None = None,
    ) -> PendingInterrupt | None:
        """
        Resolve a pending interrupt.

        Args:
            interrupt_id: Interrupt ID
            status: Resolution status
            response: User response
            resolved_by: User who resolved

        Returns:
            Updated PendingInterrupt or None
        """
        async with self._lock:
            pending = self._pending.get(interrupt_id)
            if pending is None:
                return None

            if not pending.is_pending():
                logger.warning("Interrupt %s already resolved", interrupt_id)
                return pending

            pending.status = status
            pending.response = response
            pending.resolved_at = datetime.now(UTC).replace(tzinfo=None)
            pending.resolved_by = resolved_by

            logger.info(
                "Resolved interrupt %s with status %s",
                interrupt_id, status.value
            )
            return pending

    async def approve(
        self,
        interrupt_id: str,
        response: Any = None,
        resolved_by: str | None = None,
    ) -> PendingInterrupt | None:
        """Approve an interrupt."""
        return await self.resolve(
            interrupt_id,
            InterruptStatus.APPROVED,
            response,
            resolved_by,
        )

    async def reject(
        self,
        interrupt_id: str,
        response: Any = None,
        resolved_by: str | None = None,
    ) -> PendingInterrupt | None:
        """Reject an interrupt."""
        return await self.resolve(
            interrupt_id,
            InterruptStatus.REJECTED,
            response,
            resolved_by,
        )

    async def cancel(self, interrupt_id: str) -> PendingInterrupt | None:
        """Cancel a pending interrupt."""
        return await self.resolve(interrupt_id, InterruptStatus.CANCELLED)

    async def cleanup_expired(self) -> int:
        """Remove expired interrupts."""
        async with self._lock:
            expired_ids = [
                iid for iid, pending in self._pending.items()
                if pending.is_expired()
            ]

            for iid in expired_ids:
                pending = self._pending.pop(iid, None)
                if pending:
                    pending.status = InterruptStatus.TIMEOUT

            return len(expired_ids)


# Global registry instance
_interrupt_registry: InterruptRegistry | None = None


def get_interrupt_registry() -> InterruptRegistry:
    """Get the global interrupt registry."""
    global _interrupt_registry
    if _interrupt_registry is None:
        _interrupt_registry = InterruptRegistry()
    return _interrupt_registry


class InterruptHandler:
    """
    Handler for processing interrupts in workflows.

    Provides high-level methods for waiting on and resuming
    from interrupts.
    """

    def __init__(self, registry: InterruptRegistry | None = None):
        self.registry = registry or get_interrupt_registry()

    async def wait_for_approval(
        self,
        interrupt_obj: Interrupt,
        session_id: str,
        thread_id: str,
        checkpoint_id: str | None = None,
        timeout_sec: int | None = None,
        poll_interval: float = 1.0,
    ) -> tuple[bool, Any]:
        """
        Wait for human approval of an interrupt.

        Args:
            interrupt_obj: The interrupt to wait for
            session_id: Session ID
            thread_id: Thread ID
            checkpoint_id: Checkpoint ID
            timeout_sec: Timeout in seconds
            poll_interval: Poll interval in seconds

        Returns:
            Tuple of (approved, response)
        """
        pending = await self.registry.register(
            interrupt_obj,
            session_id,
            thread_id,
            checkpoint_id,
        )

        timeout = timeout_sec or INTERRUPT_TIMEOUT_SEC
        deadline = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=timeout)

        while datetime.now(UTC).replace(tzinfo=None) < deadline:
            current = await self.registry.get(pending.id)
            if current is None:
                return False, None

            if not current.is_pending():
                approved = current.status == InterruptStatus.APPROVED
                return approved, current.response

            await asyncio.sleep(poll_interval)

        # Timeout
        await self.registry.resolve(pending.id, InterruptStatus.TIMEOUT)
        return False, None

    def create_resume_command(
        self,
        pending: PendingInterrupt,
    ) -> Command:
        """
        Create a Command to resume from an interrupt.

        Args:
            pending: The resolved PendingInterrupt

        Returns:
            Command to continue workflow
        """
        if pending.status == InterruptStatus.APPROVED:
            return Command.continue_to("__resume__", interrupt_response=pending.response)
        elif pending.status == InterruptStatus.REJECTED:
            return Command.continue_to("__rejected__", interrupt_response=pending.response)
        else:
            return Command.finish(error=f"Interrupt {pending.status.value}")


# Convenience functions for common interrupt patterns


def require_approval(
    value: Any,
    prompt: str = "Please approve this action",
    options: list[str] | None = None,
    **metadata,
) -> Interrupt:
    """
    Create an interrupt requiring approval.

    Args:
        value: Value to present for approval
        prompt: Approval prompt
        options: Optional response options
        **metadata: Additional metadata

    Returns:
        Interrupt object
    """
    options = options or ["approve", "reject"]
    return interrupt(
        value=value,
        prompt=prompt,
        options=options,
        type="approval",
        **metadata,
    )


def require_review(
    content: str,
    prompt: str = "Please review this content",
    allow_edit: bool = True,
    **metadata,
) -> Interrupt:
    """
    Create an interrupt for content review.

    Args:
        content: Content to review
        prompt: Review prompt
        allow_edit: Whether to allow editing
        **metadata: Additional metadata

    Returns:
        Interrupt object
    """
    options = ["approve", "reject"]
    if allow_edit:
        options.append("edit")

    return interrupt(
        value={"content": content, "allow_edit": allow_edit},
        prompt=prompt,
        options=options,
        type="review",
        **metadata,
    )


def require_input(
    prompt: str,
    input_type: str = "text",
    required: bool = True,
    **metadata,
) -> Interrupt:
    """
    Create an interrupt requiring user input.

    Args:
        prompt: Input prompt
        input_type: Type of input expected
        required: Whether input is required
        **metadata: Additional metadata

    Returns:
        Interrupt object
    """
    return interrupt(
        value={"input_type": input_type, "required": required},
        prompt=prompt,
        options=None,  # Free-form input
        type="input",
        **metadata,
    )


def require_selection(
    prompt: str,
    options: list[str],
    allow_multiple: bool = False,
    **metadata,
) -> Interrupt:
    """
    Create an interrupt requiring selection from options.

    Args:
        prompt: Selection prompt
        options: Available options
        allow_multiple: Allow multiple selections
        **metadata: Additional metadata

    Returns:
        Interrupt object
    """
    return interrupt(
        value={"options": options, "allow_multiple": allow_multiple},
        prompt=prompt,
        options=options,
        type="selection",
        **metadata,
    )
