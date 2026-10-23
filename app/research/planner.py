import re
from typing import List, Set
from app.research.state import SubQuery

MAX_SUBQUERIES = 4

STOP_WORDS: Set[str] = {
    "what", "is", "the", "how", "does", "why", "can", "are", "and", "or",
    "in", "of", "to", "for", "with", "a", "an", "explain", "tell", "me",
    "about", "please", "overview", "compare", "between",
}


def plan_research(question: str, max_subqueries: int = MAX_SUBQUERIES) -> List[SubQuery]:
    """
    Decomposes a user's research question into a bounded set of focused subqueries.

    Args:
        question: User's research question.
        max_subqueries: Maximum number of subqueries allowed (default: 4).

    Returns:
        List of SubQuery objects.

    Raises:
        ValueError: If question is empty or insufficient.
    """
    if not question or not question.strip():
        raise ValueError("Research question cannot be empty.")

    cleaned_question = question.strip()
    if len(cleaned_question) < 4:
        raise ValueError("Research question is too short to construct a research plan.")

    subqueries: List[SubQuery] = []

    # 1. Primary overall query
    subqueries.append(
        SubQuery(
            id="Q1",
            query_text=cleaned_question,
            intent="Gather broad overview and primary background information.",
        )
    )

    # 2. Extract key topical words
    words = [
        re.sub(r"[^\w]", "", w.lower())
        for w in cleaned_question.split()
        if len(w) > 2 and re.sub(r"[^\w]", "", w.lower()) not in STOP_WORDS
    ]

    # 3. Formulate comparative / technical subqueries if keywords exist
    if words:
        primary_topic = " ".join(words[:3])
        if len(subqueries) < max_subqueries:
            subqueries.append(
                SubQuery(
                    id=f"Q{len(subqueries) + 1}",
                    query_text=f"{primary_topic} architecture and performance",
                    intent="Investigate technical mechanisms and architectural characteristics.",
                )
            )

        if len(subqueries) < max_subqueries and len(words) >= 2:
            subqueries.append(
                SubQuery(
                    id=f"Q{len(subqueries) + 1}",
                    query_text=f"{primary_topic} limitations and challenges",
                    intent="Identify documented limitations, trade-offs, or known controversies.",
                )
            )

    return subqueries[:max_subqueries]
