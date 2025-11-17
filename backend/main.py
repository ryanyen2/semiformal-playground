"""
FastAPI backend for bidirectional semiformal programming (IR-based).

Clean architecture using only:
- ast_parser.py for parsing semiformal code to IR
- diff_generator.py for LLM code generation with comment anchors
- ir_sync.py for bidirectional synchronization
- fine_grained_mapper.py for AST-level mapping
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import os
from dotenv import load_dotenv
load_dotenv()

from ast_parser import parse_semiformal
from ir_sync import IRSync, AutoSync, SyncResult
from diff_generator import DiffGenerator
from skeleton_generator import generate_skeleton
from fine_grained_mapper import FineGrainedMapper, ASTMapping
from ir import ProgramIR, IRNode, NodeType, NodeStatus

app = FastAPI(title="Semiformal Programming API (IR-based)")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
auto_sync = AutoSync()


# Request/Response Models

class ParseRequest(BaseModel):
    code: str


class ParseResponse(BaseModel):
    ir: Dict[str, Any]
    incomplete_nodes: List[Dict[str, Any]]
    skeleton_code: str


class GenerateRequest(BaseModel):
    semiformal_code: str


class GenerateResponse(BaseModel):
    generated_code: str
    ir: Dict[str, Any]
    mappings: Dict[str, Dict[str, Any]]  # node_id -> ASTMapping


class EditSemiformalRequest(BaseModel):
    semiformal_code: str
    edit_type: str  # 'code_node_edit' or 'nl_phrase_edit'
    node_id: Optional[str] = None
    new_content: Optional[str] = None


class EditSemiformalResponse(BaseModel):
    updated_code: str
    needs_regeneration: bool
    affected_nodes: List[str]
    message: str


class EditCodeRequest(BaseModel):
    semiformal_code: str
    generated_code: str
    old_code: str
    new_code: str


class EditCodeResponse(BaseModel):
    updated_semiformal: str
    message: str


# API Endpoints

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Semiformal Programming API (IR-based)",
        "version": "2.0.0"
    }


@app.post("/parse", response_model=ParseResponse)
async def parse_code(request: ParseRequest):
    """
    Parse semiformal code and build IR.

    Returns IR, incomplete nodes, and instant skeleton.
    """
    try:
        # Parse to IR
        ir = parse_semiformal(request.code)

        # Generate instant skeleton (no LLM)
        skeleton = generate_skeleton(ir)

        # Get incomplete nodes
        incomplete = ir.get_incomplete_nodes()

        return ParseResponse(
            ir=ir_to_dict(ir),
            incomplete_nodes=[node_to_dict(n) for n in incomplete],
            skeleton_code=skeleton
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse error: {str(e)}")


@app.post("/generate", response_model=GenerateResponse)
async def generate_code(request: GenerateRequest):
    """
    Generate complete Python code from semiformal specification.

    Uses LLM to generate code with comment anchors for mapping.
    """
    try:
        # Parse to IR
        ir = parse_semiformal(request.semiformal_code)

        # Generate code with LLM
        generator = DiffGenerator()
        generated_code, diffs = generator.generate_from_ir(ir)

        # Create mappings
        mapper = FineGrainedMapper(generated_code)
        mappings = mapper.map_all_nodes(ir)

        # Update auto_sync state
        auto_sync.sync.set_ir(ir)
        auto_sync.last_spec = request.semiformal_code
        auto_sync.last_code = generated_code

        return GenerateResponse(
            generated_code=generated_code,
            ir=ir_to_dict(ir),
            mappings={nid: mapping_to_dict(m) for nid, m in mappings.items()}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")


@app.post("/edit/semiformal", response_model=EditSemiformalResponse)
async def edit_semiformal(request: EditSemiformalRequest):
    """
    Handle edits to semiformal code.

    Two modes:
    1. code_node_edit: Direct structural edit (no LLM, fast)
    2. nl_phrase_edit: NL phrase changed, needs LLM refinement
    """
    try:
        if request.edit_type == 'code_node_edit':
            # Direct structural transformation (fast path)
            result = auto_sync.sync.merge_and_transform(request.semiformal_code)

            # Generate skeleton
            ir = auto_sync.sync.get_ir()
            skeleton = generate_skeleton(ir)

            return EditSemiformalResponse(
                updated_code=skeleton,
                needs_regeneration=False,
                affected_nodes=[],
                message="Applied structural transformation"
            )

        elif request.edit_type == 'nl_phrase_edit':
            # NL phrase changed, trigger LLM refinement
            result = auto_sync.sync.sync_spec_change(
                auto_sync.last_spec,
                request.semiformal_code
            )

            return EditSemiformalResponse(
                updated_code=result.updated_source,
                needs_regeneration=True,
                affected_nodes=result.affected_nodes,
                message=result.message
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid edit_type: {request.edit_type}"
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Edit error: {str(e)}")


@app.post("/edit/code", response_model=EditCodeResponse)
async def edit_code(request: EditCodeRequest):
    """
    Handle edits to generated code.

    Syncs changes back to semiformal spec using PUT transformation.
    """
    try:
        result = auto_sync.sync.sync_code_change(
            request.semiformal_code,
            request.old_code,
            request.new_code
        )

        return EditCodeResponse(
            updated_semiformal=result.updated_source,
            message=result.message
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Code edit error: {str(e)}")


@app.post("/skeleton")
async def generate_skeleton_endpoint(semiformal_code: str):
    """
    Generate instant skeleton without LLM.

    This is called on every keystroke for fast feedback.
    """
    try:
        # Parse to IR
        ir = parse_semiformal(semiformal_code)

        # Generate skeleton
        skeleton = generate_skeleton(ir)

        # Update auto_sync
        auto_sync.sync.set_ir(ir)
        auto_sync.last_spec = semiformal_code

        return {
            "skeleton_code": skeleton,
            "incomplete_count": len(ir.get_incomplete_nodes())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Skeleton error: {str(e)}")


@app.post("/mappings")
async def get_mappings(semiformal_code: str, generated_code: str):
    """
    Get fine-grained mappings between IR nodes and AST nodes.

    Used by frontend for highlighting and navigation.
    """
    try:
        # Parse to IR
        ir = parse_semiformal(semiformal_code)

        # Create mapper
        mapper = FineGrainedMapper(generated_code)
        mappings = mapper.map_all_nodes(ir)

        return {
            "mappings": {nid: mapping_to_dict(m) for nid, m in mappings.items()},
            "ir": ir_to_dict(ir)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mapping error: {str(e)}")


# Helper functions

def ir_to_dict(ir: ProgramIR) -> Dict[str, Any]:
    """Convert ProgramIR to dictionary for JSON serialization."""
    return {
        "nodes": {nid: node_to_dict(node) for nid, node in ir.nodes.items()},
        "spec_source": ir.spec_source,
        "code_source": ir.code_source,
        "dependency_graph": {nid: list(deps) for nid, deps in ir.dependency_graph.items()}
    }


def node_to_dict(node: IRNode) -> Dict[str, Any]:
    """Convert IRNode to dictionary."""
    return {
        "id": node.id,
        "type": node.node_type.value,
        "name": node.name,
        "status": node.status.value,
        "spec_text": node.spec_text,
        "code_text": node.code_text,
        "spec_location": location_to_dict(node.spec_location) if node.spec_location else None,
        "code_location": location_to_dict(node.code_location) if node.code_location else None,
        "metadata": node.metadata
    }


def location_to_dict(loc) -> Dict[str, int]:
    """Convert SourceLocation to dictionary."""
    return {
        "line": loc.line,
        "col": loc.col,
        "end_line": loc.end_line,
        "end_col": loc.end_col
    }


def mapping_to_dict(mapping: ASTMapping) -> Dict[str, Any]:
    """Convert ASTMapping to dictionary."""
    return {
        "node_id": mapping.node_id,
        "line": mapping.line,
        "col_start": mapping.col_start,
        "col_end": mapping.col_end,
        "code_text": mapping.code_text,
        "confidence": mapping.confidence,
        "mapping_type": mapping.mapping_type
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
