"""
FastAPI backend for bidirectional semiformal programming.

Provides endpoints for:
- Parsing incomplete Python code
- Generating complete code with LLM
- Synchronizing changes bidirectionally
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import os
from dotenv import load_dotenv
load_dotenv()

from parser import parse_incomplete_python
from generator import CodeGenerator, IncrementalGenerator
from sync import BidirectionalSync, Edit, create_edit_from_spec_change

app = FastAPI(title="Semiformal Programming API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
code_generator = CodeGenerator()
incremental_generator = IncrementalGenerator(code_generator)
sync_manager = BidirectionalSync()


# Request/Response Models

class ParseRequest(BaseModel):
    code: str


class ParseResponse(BaseModel):
    incomplete_parts: List[Dict[str, Any]]
    stubs: List[Dict[str, Any]]
    annotated_code: str


class GenerateRequest(BaseModel):
    semiformal_code: str


class GenerateResponse(BaseModel):
    generated_code: str
    incomplete_parts: List[Dict[str, Any]]


class SyncRequest(BaseModel):
    direction: str  # 'spec_to_code' or 'code_to_spec'
    edit_type: str
    location: str
    content: str
    line: Optional[int] = None
    spec_code: str
    generated_code: str


class SyncResponse(BaseModel):
    updated_code: str
    needs_regeneration: bool
    regeneration_targets: List[str]
    message: str


class RegenerateRequest(BaseModel):
    function_name: str
    current_code: str
    constraint: str
    constraint_type: str


class RegenerateResponse(BaseModel):
    updated_code: str


# API Endpoints

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Semiformal Programming API",
        "version": "0.1.0"
    }


@app.post("/parse", response_model=ParseResponse)
async def parse_code(request: ParseRequest):
    """
    Parse incomplete Python code and identify parts that need completion.

    Returns:
        - incomplete_parts: List of incomplete code elements
        - stubs: Stub declarations to be created
        - annotated_code: Code with stubs inserted
    """
    try:
        result = parse_incomplete_python(request.code)
        return ParseResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parsing error: {str(e)}")


@app.post("/edit/semiformal", response_model=EditResponse)
async def edit_semiformal(request: EditRequest):
    """
    Generate complete Python code from semiformal specification.

    Uses LLM to fill in incomplete parts (functions, variables, NL text).
    """
    try:
        # First parse to identify incomplete parts
        parse_result = parse_incomplete_python(request.semiformal_code)

        # Generate complete code
        generated_code = incremental_generator.generate_from_parse_result(
            parse_result,
            request.semiformal_code
        )

        return GenerateResponse(
            generated_code=generated_code,
            incomplete_parts=parse_result['incomplete_parts']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Edit error: {str(e)}")


@app.post("/sync", response_model=SyncResponse)
async def sync_changes(request: SyncRequest):
    """
    Synchronize changes bidirectionally between spec and generated code.

    Supports:
    - spec_to_code: parameter additions, renames, statement insertions
    - code_to_spec: surfacing edited blocks back to spec
    """
    try:
        edit = Edit(
            type=request.edit_type,
            location=request.location,
            content=request.content,
            line=request.line
        )

        if request.direction == 'spec_to_code':
            result = sync_manager.sync_spec_to_code(
                edit,
                request.spec_code,
                request.generated_code
            )
        elif request.direction == 'code_to_spec':
            result = sync_manager.sync_code_to_spec(
                edit,
                request.spec_code,
                request.generated_code
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid direction: {request.direction}"
            )

        return SyncResponse(
            updated_code=result.updated_code,
            needs_regeneration=result.needs_regeneration,
            regeneration_targets=result.regeneration_targets,
            message=result.message
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hole filling error: {str(e)}")


@app.post("/regenerate", response_model=RegenerateResponse)
async def regenerate_function(request: RegenerateRequest):
    """
    Regenerate a function with additional constraints.

    Used when spec changes require LLM to regenerate the implementation.
    """
    try:
        updated_code = code_generator.regenerate_with_constraints(
            func_name=request.function_name,
            current_code=request.current_code,
            new_constraint=request.constraint,
            constraint_type=request.constraint_type
        )

        return RegenerateResponse(updated_code=updated_code)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Regeneration error: {str(e)}"
        )


@app.post("/generate-expression")
async def generate_expression(
    var_name: str,
    nl_description: str,
    context: str
):
    """Generate a Python expression from natural language description."""
    try:
        expression = code_generator.generate_expression(
            var_name=var_name,
            nl_description=nl_description,
            context=context
        )
        return {"expression": expression}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Expression generation error: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

