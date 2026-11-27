"""Co-Camp — the Manager Assistant for SPMS, developed by Michael Helmy.

Co-Camp is a small, specialized assistant for the SPMS (Super Property
Management System) app. This package carries the persona constants and the
tooling that produces the fine-tuned training data and trains the small
specialized intent router.
"""

from .persona import NAME, DEVELOPER, ROLE

__all__ = ["NAME", "DEVELOPER", "ROLE"]
