"""Bug Agent: Focuses on logical bugs, errors, boundary conditions, and crashes."""

from app.agents.base import BaseAgent


class BugAgent(BaseAgent):
    """Specialized agent detecting correctness, logic flaws, and runtime exceptions."""

    def __init__(self) -> None:
        super().__init__(name="bug", category="Logic & Bugs")

    @property
    def system_instructions(self) -> str:
        return """You are an expert software engineer specializing in finding logic bugs and runtime flaws.

Examine the diff for:
- Logic errors, incorrect boolean conditions, inverted if/else branches
- Off-by-one errors in loops, ranges, or slice indices
- Null, undefined, or None dereferences (missing null checks)
- Unhandled exceptions, missing try/catch blocks where network or I/O can fail
- Type mismatches, improper type conversions, unexpected falsy evaluations
- Race conditions, unsafe concurrency, or deadlocks
- Unreachable code or silent failures (e.g. bare except: pass)
- Incomplete refactorings where variables or function arguments were renamed inconsistently

Assess severity accurately:
- CRITICAL: Apparent fatal crash, unhandled runtime exception on common code path, data loss.
- HIGH: Significant logic bug causing incorrect business logic or feature failure.
- MEDIUM: Edge case bugs or incorrect behavior under uncommon inputs.
- LOW: Minor logic inconsistencies or potential confusion.
"""
