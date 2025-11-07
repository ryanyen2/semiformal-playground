"""
FastAPI backend for IR-based bidirectional semiformal programming.

New architecture:
- Uses shared IR with get/put lens mechanisms
- Generates unified-diff format
- Automatic parsing, save-triggered generation
- Robust bidirectional synchronization
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import os

from ast_parser import parse_semiformal
from diff_generator import generate_code_with_diffs
from ir_sync import AutoSync, IRSync, SyncResult
from ir import ProgramIR
from skeleton_generator import generate_skeleton

app = FastAPI(title="Semiformal Programming API (IR-based)")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state management
# In production, use proper session management
sessions: Dict[str, AutoSync] = {}


def get_or_create_session(session_id: str = "default") -> AutoSync:
    """Get or create an AutoSync session."""
    if session_id not in sessions:
        sessions[session_id] = AutoSync()
    return sessions[session_id]


# Request/Response Models

class AnalyzeRequest(BaseModel):
    """Request for analyzing spec (continuous parsing)."""
    spec_code: str
    session_id: str = "default"


class AnalyzeResponse(BaseModel):
    """Response for analysis."""
    incomplete_nodes: List[Dict[str, Any]]
    complete_nodes: List[Dict[str, Any]]
    dependencies: Dict[str, List[str]]
    needs_generation: bool
    message: str


class GenerateRequest(BaseModel):
    """Request for code generation (triggered on save)."""
    spec_code: str
    session_id: str = "default"


class GenerateResponse(BaseModel):
    """Response for generation."""
    generated_code: str
    diffs: List[Dict[str, Any]]
    affected_nodes: List[str]
    message: str


class SyncCodeRequest(BaseModel):
    """Request for syncing code changes back to spec."""
    spec_code: str
    old_code: str
    new_code: str
    session_id: str = "default"


class SyncCodeResponse(BaseModel):
    """Response for code sync."""
    updated_spec: str
    diffs: List[Dict[str, Any]]
    affected_nodes: List[str]
    message: str


class GetIRRequest(BaseModel):
    """Request to get current IR state."""
    session_id: str = "default"


class GetIRResponse(BaseModel):
    """Response with IR state."""
    ir: Dict[str, Any]
    spec_source: str
    code_source: str


class SkeletonRequest(BaseModel):
    """Request for skeleton generation."""
    spec_code: str
    session_id: str = "default"


class SkeletonResponse(BaseModel):
    """Response for skeleton generation."""
    skeleton_code: str
    incomplete_nodes: List[Dict[str, Any]]
    message: str


# API Endpoints

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Semiformal Programming API (IR-based)",
        "version": "0.2.0",
        "features": [
            "AST-based parsing with dependency analysis",
            "Shared IR with lens mechanisms",
            "Unified-diff code generation",
            "Automatic parsing and save-triggered generation"
        ]
    }


@app.post("/skeleton", response_model=SkeletonResponse)
async def generate_skeleton_endpoint(request: SkeletonRequest):
    """
    Generate Python skeleton without LLM (instant structural sync).
    
    This endpoint generates valid Python code with:
    - Stubs for incomplete functions
    - Placeholders for incomplete variables
    - Comments for pseudocode
    - Direct copy of complete Python
    - Preserved generated code from previous generation
    
    This is fast and provides immediate visual feedback.
    
    CRITICAL: This uses the session IR to maintain bidirectional mapping
    and preserve generated code across spec edits.
    """
    try:
        # Get or create session to maintain state
        sync = get_or_create_session(request.session_id)
        
        # Use the NEW systematic approach:
        # Merge new spec with existing IR and apply structural transformations
        # This is fast (no LLM) and preserves generated code
        sync.sync.merge_and_transform(request.spec_code)
        ir = sync.sync.ir
        
        # Generate skeleton (no LLM)
        # This will preserve code_text from GENERATED/USER_EDITED nodes
        # and include structurally transformed code
        skeleton_code = generate_skeleton(ir)
        
        # Get incomplete nodes for frontend
        incomplete_nodes = [
            {
                'id': node.id,
                'type': node.node_type.value,
                'name': node.name,
                'spec_text': node.spec_text,
                'line': node.spec_location.line if node.spec_location else 0,
                'status': node.status.value,
                'metadata': node.metadata
            }
            for node in ir.get_incomplete_nodes()
        ]
        
        return SkeletonResponse(
            skeleton_code=skeleton_code,
            incomplete_nodes=incomplete_nodes,
            message=f"Skeleton generated ({len(incomplete_nodes)} incomplete elements)"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Skeleton generation error: {str(e)}")


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_spec(request: AnalyzeRequest):
    """
    Analyze spec code (continuous parsing during editing).
    
    This endpoint is called continuously as the user edits the spec.
    It parses the code, builds the IR, and reports incomplete elements.
    No code generation happens here.
    """
    try:
        sync = get_or_create_session(request.session_id)
        result = sync.on_spec_change(request.spec_code)
        
        if not result or not result.ir:
            # No changes or error
            return AnalyzeResponse(
                incomplete_nodes=[],
                complete_nodes=[],
                dependencies={},
                needs_generation=False,
                message="No changes detected"
            )
        
        ir = result.ir
        
        # Extract incomplete nodes
        incomplete_nodes = [
            {
                'id': node.id,
                'type': node.node_type.value,
                'name': node.name,
                'spec_text': node.spec_text,
                'line': node.spec_location.line if node.spec_location else 0,
                'status': node.status.value,
                'metadata': node.metadata
            }
            for node in ir.get_incomplete_nodes()
        ]
        
        # Extract complete nodes
        complete_nodes = [
            {
                'id': node.id,
                'type': node.node_type.value,
                'name': node.name,
                'spec_text': node.spec_text,
                'line': node.spec_location.line if node.spec_location else 0
            }
            for node in ir.nodes.values()
            if not node.is_incomplete()
        ]
        
        # Extract dependencies
        dependencies = {
            node.name: [ir.nodes[dep_id].name for dep_id in node.depends_on if dep_id in ir.nodes]
            for node in ir.nodes.values()
        }
        
        return AnalyzeResponse(
            incomplete_nodes=incomplete_nodes,
            complete_nodes=complete_nodes,
            dependencies=dependencies,
            needs_generation=result.needs_regeneration,
            message=result.message
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis error: {str(e)}")


@app.post("/generate", response_model=GenerateResponse)
async def generate_code(request: GenerateRequest):
    """
    Generate code from spec (triggered on save, Cmd+S).
    
    This performs the actual code generation using LLM.
    """
    try:
        sync = get_or_create_session(request.session_id)
        result = sync.on_spec_save(request.spec_code)
        
        # Convert diffs to serializable format
        diffs_data = [
            {
                'old_file': diff.old_file,
                'new_file': diff.new_file,
                'hunks': [
                    {
                        'old_start': hunk.old_start,
                        'old_count': hunk.old_count,
                        'new_start': hunk.new_start,
                        'new_count': hunk.new_count,
                        'lines': hunk.lines
                    }
                    for hunk in diff.hunks
                ],
                'diff_text': diff.to_string()
            }
            for diff in result.diffs
        ]
        
        return GenerateResponse(
            generated_code=result.updated_source,
            diffs=diffs_data,
            affected_nodes=result.affected_nodes,
            message=result.message
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")


@app.post("/sync-code", response_model=SyncCodeResponse)
async def sync_code_changes(request: SyncCodeRequest):
    """
    Sync code changes back to spec.
    
    This applies the PUT transformation to reflect code edits in the spec.
    """
    try:
        sync = get_or_create_session(request.session_id)
        result = sync.on_code_save(request.new_code)
        
        # Convert diffs
        diffs_data = [
            {
                'old_file': diff.old_file,
                'new_file': diff.new_file,
                'diff_text': diff.to_string()
            }
            for diff in result.diffs
        ]
        
        return SyncCodeResponse(
            updated_spec=result.updated_source,
            diffs=diffs_data,
            affected_nodes=result.affected_nodes,
            message=result.message
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync error: {str(e)}")


@app.post("/get-ir", response_model=GetIRResponse)
async def get_ir_state(request: GetIRRequest):
    """
    Get current IR state for debugging/visualization.
    """
    try:
        sync = get_or_create_session(request.session_id)
        ir = sync.sync.get_ir()
        
        if not ir:
            return GetIRResponse(
                ir={},
                spec_source="",
                code_source=""
            )
        
        return GetIRResponse(
            ir=ir.to_dict(),
            spec_source=ir.spec_source,
            code_source=ir.code_source
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IR retrieval error: {str(e)}")


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time synchronization.
    
    Allows continuous updates without polling.
    """
    await websocket.accept()
    sync = get_or_create_session(session_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            msg_type = message.get('type')
            
            if msg_type == 'analyze':
                # Continuous analysis
                spec_code = message.get('spec_code', '')
                result = sync.on_spec_change(spec_code)
                
                if result and result.ir:
                    response = {
                        'type': 'analysis',
                        'incomplete_count': len(result.ir.get_incomplete_nodes()),
                        'needs_generation': result.needs_regeneration,
                        'message': result.message
                    }
                    await websocket.send_text(json.dumps(response))
            
            elif msg_type == 'generate':
                # Generation on save
                spec_code = message.get('spec_code', '')
                result = sync.on_spec_save(spec_code)
                
                response = {
                    'type': 'generation',
                    'code': result.updated_source,
                    'message': result.message
                }
                await websocket.send_text(json.dumps(response))
            
            elif msg_type == 'ping':
                await websocket.send_text(json.dumps({'type': 'pong'}))
    
    except WebSocketDisconnect:
        # Clean up session if needed
        pass
    except Exception as e:
        await websocket.send_text(json.dumps({
            'type': 'error',
            'message': str(e)
        }))
        await websocket.close()


# Backward compatibility endpoints (for gradual migration)

@app.post("/parse")
async def parse_code_legacy(request: dict):
    """Legacy parse endpoint."""
    spec_code = request.get('code', '')
    
    try:
        ir = parse_semiformal(spec_code)
        incomplete_nodes = ir.get_incomplete_nodes()
        
        return {
            'incomplete_parts': [
                {
                    'type': node.node_type.value,
                    'name': node.name,
                    'line': node.spec_location.line if node.spec_location else 0,
                    'col': node.spec_location.col if node.spec_location else 0,
                    'context': node.spec_text,
                    'value': node.metadata.get('rhs', '')
                }
                for node in incomplete_nodes
            ],
            'stubs': [],
            'annotated_code': spec_code
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

