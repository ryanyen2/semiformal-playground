"""
MVP FastAPI backend for bidirectional semiformal programming.

Uses the new MVP implementation with:
- Phase 1: Direct AST edits
- Phase 2: Placeholder support
- Phase 3: Hole syntax and LLM generation
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
from dotenv import load_dotenv
load_dotenv()

from editor import BidirectionalEditor
from edit_router import Edit

app = FastAPI(title="Semiformal Programming MVP API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize MVP editor
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
editor = BidirectionalEditor(openai_api_key=OPENAI_API_KEY)


# Request/Response Models

class InitializeRequest(BaseModel):
    semiformal_code: str


class InitializeResponse(BaseModel):
    python_code: str
    nodes: List[Dict[str, Any]]
    mappings: List[Dict[str, Any]]
    message: str


class EditRequest(BaseModel):
    location: str
    content: str
    old_content: Optional[str] = None
    line: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    semiformal_code: str  # Current semiformal code


class EditResponse(BaseModel):
    success: bool
    python_code: str
    message: str
    needs_regeneration: bool = False
    regeneration_targets: List[str] = []


class StateResponse(BaseModel):
    semiformal_code: str
    python_code: str
    nodes: List[Dict[str, Any]]
    mappings: List[Dict[str, Any]]
    has_llm: bool


# API Endpoints

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Semiformal Programming API",
        "version": "1.0.0",
        "phases": ["Phase 1: Direct AST edits", "Phase 2: LLM-based code generation"],
        "has_openai": OPENAI_API_KEY is not None
    }


@app.post("/initialize", response_model=InitializeResponse)
async def initialize(request: InitializeRequest):
    """
    Initialize the editor with semiformal code.

    Parses the code into intent nodes and generates initial Python code.

    Args:
        semiformal_code: The semiformal Python code with NL, holes, etc.

    Returns:
        - python_code: Generated Python code
        - nodes: List of parsed intent nodes
        - mappings: Node→code mappings
        - message: Status message
    """
    try:
        result = editor.initialize(request.semiformal_code)
        return InitializeResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Initialization error: {str(e)}")


@app.post("/edit/semiformal", response_model=EditResponse)
async def edit_semiformal(request: EditRequest):
    """
    Apply an edit to semiformal code and update Python code.

    Supports Phase 1-3 edits:
    - Direct edits: renames, operator changes, literal changes
    - Placeholder edits: add variables with unknown values
    - Hole filling: LLM-based code generation

    Args:
        location: Location of edit (function name, line num, etc.)
        content: New content
        old_content: Previous content (for renames)
        line: Line number (for line-based edits)
        metadata: Additional edit metadata
        semiformal_code: Updated semiformal code

    Returns:
        - success: Whether edit succeeded
        - python_code: Updated Python code
        - message: Result message
        - needs_regeneration: If full regeneration needed
        - regeneration_targets: What needs regeneration
    """
    try:
        previous_semiformal = editor.semiformal_code
        editor.semiformal_code = request.semiformal_code

        metadata: Dict[str, Any] = request.metadata or {}
        if "previous_semiformal_code" not in metadata:
            metadata["previous_semiformal_code"] = previous_semiformal

        if editor.translator is None:
            init_result = editor.initialize(request.semiformal_code)
            return EditResponse(
                success=True,
                python_code=init_result["python_code"],
                message=init_result["message"],
                needs_regeneration=False,
                regeneration_targets=[],
            )

        edit = Edit(
            location=request.location,
            content=request.content,
            old_content=request.old_content,
            line=request.line,
            metadata=metadata
        )

        print('edit', edit)

        # Apply edit
        result = editor.on_semiformal_edit(edit)

        return EditResponse(**result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Edit error: {str(e)}")


@app.post("/edit/python")
async def edit_python(request: EditRequest):
    """
    Handle edits to generated Python code.

    Decides whether to propagate changes back to semiformal code.

    Args:
        location: Location of edit
        content: New content
        line: Line number

    Returns:
        - success: Whether edit was processed
        - propagate: Whether it should propagate to semiformal
        - message: Result message
        - suggestion: Optional suggestion for semiformal update
    """
    try:
        edit = Edit(
            location=request.location,
            content=request.content,
            old_content=request.old_content,
            line=request.line,
            metadata=request.metadata or {}
        )

        result = editor.on_python_edit(edit)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Python edit error: {str(e)}")


@app.get("/state", response_model=StateResponse)
async def get_state():
    """
    Get current editor state.

    Returns:
        - semiformal_code: Current semiformal code
        - python_code: Current Python code
        - nodes: Parsed intent nodes
        - mappings: Node→code mappings
        - has_llm: Whether LLM features are available
    """
    try:
        state = editor.get_state()
        return StateResponse(**state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"State retrieval error: {str(e)}")



if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
