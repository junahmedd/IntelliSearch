from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolName(str, Enum):
    """Available tools that the agent decision policy can choose."""

    INSPECT_PROJECT = "inspect_project"
    SEARCH_CODE = "search_code"
    FINISH = "finish"


class EvidenceItem(BaseModel):
    """
    Factual evidence observed directly in code files.
    Distinguished strictly from hypotheses or suspected root causes.
    """

    file: str = Field(..., description="Relative path of file containing evidence.")
    line_number: int = Field(..., description="1-indexed line number of the match.")
    line_content: str = Field(..., description="Exact source code line.")
    search_query: str = Field(..., description="Query string that located this line.")


class ToolObservation(BaseModel):
    """The factual result returned after executing a specific tool action."""

    tool_name: str
    parameters: Dict[str, Any]
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class InvestigationStep(BaseModel):
    """A single cycle of thought, action, and observation in the agent's workflow."""

    step_number: int
    thought: str = Field(..., description="Agent reasoning before taking the action.")
    action: str = Field(..., description="Tool name chosen for execution.")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters passed to the selected tool.",
    )
    observation: ToolObservation


class InvestigationReport(BaseModel):
    """
    Final synthesized outcome of the bounded investigation.
    Clearly separates observed factual evidence from suspected hypotheses.
    """

    bug_description: str
    status: str = Field(
        ...,
        description="'completed', 'max_steps_reached', or 'error'",
    )
    total_steps: int
    steps_taken: List[InvestigationStep] = Field(default_factory=list)
    observed_evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="Factual, verifiable evidence observed in code files.",
    )
    suspected_root_cause: Optional[str] = Field(
        default=None,
        description="Hypothesized explanation based on observed evidence (not confirmed as fact).",
    )
    summary: str = Field(
        ...,
        description="Human-readable synthesis of the investigation results.",
    )
