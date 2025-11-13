# Bidirectional Synchronization: Mapping Issues & Current Status

## Overview
This document details the specific mapping and synchronization issues in the bidirectional programming system, focusing on why the LHS transformation test is failing.

## The Test Case: x → x,y Transformation

### What Should Happen

**Initial State:**
```python
# Spec (left):
x = split dataset into training and test sets

# Generated Code (right):
def process_data(*args, **kwargs):
    """TODO: Implement process_data"""
    raise NotImplementedError("process_data needs implementation")

def transform(*args, **kwargs):
    """TODO: Implement transform"""
    raise NotImplementedError("transform needs implementation")

result = process_data(raw_input)
x = (x_train, x_test)  # LLM generated
output = transform(x)
print(result, x, output)
```

**User Edits Spec to:**
```python
# Spec (left):
x,y = split dataset into training and test sets
```

**Expected Result:**
```python
# Generated Code (right):
(x, y) = (x_train, x_test)  # LHS changed, code preserved!
```

### Why This Matters

This test validates:
1. **Change detection**: Parser correctly identifies LHS changed from `['x']` to `['x', 'y']`
2. **Structural transformation**: Code AST is updated without LLM
3. **Code preservation**: Generated code `(x_train, x_test)` is kept, not reverted to placeholder
4. **Bidirectional mapping**: System knows which code corresponds to which spec node

---

## Current Implementation Status

### ✅ What's Working

#### 1. IR Structure & Representation
- **Status**: FULLY IMPLEMENTED
- **Files**: `backend/ir.py` (562 lines)
- **Key features**:
  - IRNode with dual representation (spec + code)
  - NodeStatus tracking (INCOMPLETE → GENERATED → NEEDS_REGEN)
  - Metadata storage for LHS, RHS, signatures
  - Lens-based transformation framework

#### 2. Parser (AST-based & line-by-line)
- **Status**: FULLY IMPLEMENTED  
- **Files**: `backend/ast_parser.py` (930 lines)
- **Key features**:
  - Two parsing strategies (AST + line-by-line fallback)
  - Distinction between NL expressions and Python with undefined references
  - Multiple variable assignment support (x, y = ...)
  - Dependency graph building
  - Signature extraction and comparison

#### 3. Skeleton Generator
- **Status**: FULLY IMPLEMENTED
- **Files**: `backend/skeleton_generator.py` (372 lines)
- **Key features**:
  - Three-phase generation (stubs → functions → statements)
  - Code preservation priority (GENERATED > SYNCED > INCOMPLETE)
  - Proper enum comparison (using `.value` instead of identity)
  - Code location tracking for bidirectional mapping

#### 4. Change Detection (Tree Diff)
- **Status**: FULLY IMPLEMENTED
- **Files**: `backend/ast_operations.py` (444 lines)
- **Key features**:
  - ASTMapper for bidirectional mapping
  - TreeDiffer for detecting LHS_CHANGED, SIGNATURE_CHANGED, etc.
  - Match by line + type (not name)
  - LHS extraction from metadata

#### 5. AST-Level Transformation
- **Status**: FULLY IMPLEMENTED
- **Files**: `backend/ast_operations.py` (StructuralTransformer class)
- **Key features**:
  - `_apply_lhs_change()` transforms code AST for x → x,y
  - `_apply_signature_change()` for function signature updates
  - AST unparsing for code generation
  - Proper location fixing

### 🚧 What's Partially Implemented

#### 1. Session State Management
- **Status**: IMPLEMENTED BUT INTEGRATION ISSUES
- **Files**: `backend/main.py`, `backend/ir_sync.py`
- **Issues**:
  - Session IR created, but not always used
  - `/skeleton` endpoint may not be merging correctly
  - State not preserved across API calls in some paths

#### 2. Synchronization Flow
- **Status**: IMPLEMENTED BUT NOT FULLY WIRED
- **Files**: `backend/ir_sync.py`
- **Methods**:
  - `merge_and_transform()` - Phase 1 (instant transformation)
  - `sync_spec_change()` - Full sync with LLM
  - `_apply_structural_transformations()` - Applies changes
- **Issues**:
  - May not be called in correct order
  - Transformation results may not be used in skeleton generation

#### 3. Code → Spec Sync (PUT)
- **Status**: INTERFACE DEFINED, NOT WIRED
- **Files**: `backend/ir_sync.py` (lines 159-207)
- **Missing**:
  - Frontend integration
  - LLM-assisted intent extraction
  - Spec update with NL annotation

### ❌ What's Missing or Broken

#### 1. Integration in API Endpoint
- **Location**: `backend/main.py` `/skeleton` endpoint
- **Problem**: Unclear if `merge_and_transform()` is called before skeleton generation
- **Impact**: Structural transformations not applied during continuous edits

#### 2. Test Execution
- **Location**: `test_lhs_change.py`
- **Problem**: Test hits LLM generation (calls OpenAI API)
- **Expected**: Should work without API when using structural transformation
- **Root cause**: `sync_spec_change()` directly calls `generate_from_ir()` which needs LLM

#### 3. Frontend Integration
- **Location**: `frontend/src/api.ts`
- **Missing**: 
  - Proper session ID handling
  - Code → Spec sync API calls
  - Visualization of transformations vs generation

---

## Detailed Mapping Architecture

### Data Flow for LHS Change

```
User Input: "x,y = split dataset..."
        ↓
┌─────────────────────────────────────────────────────────┐
│ STEP 1: Parse New Spec                                  │
│ - Create new IRNode with metadata['lhs'] = ['x', 'y']  │
│ - Line number stays same (line 3)                      │
│ - NodeType: NL_EXPRESSION (natural language)            │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ STEP 2: Tree Diff Detection                             │
│ - Old node: NL_EXPRESSION at line 3 with LHS ['x']    │
│ - New node: NL_EXPRESSION at line 3 with LHS ['x','y']│
│ - Match by (line, type) → Found match!                 │
│ - Detect: LHS_CHANGED                                   │
│ - Metadata: old_lhs=['x'], new_lhs=['x','y']          │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ STEP 3: Merge IR                                        │
│ - old_ir.merge_from_spec_update(new_ir)               │
│ - Updates node: spec_text, metadata, signature         │
│ - Preserves: node.code_text, node.status              │
│ - Keeps: code_location, code_ast                       │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ STEP 4: Apply Structural Transformation                │
│ - StructuralTransformer.apply_change(LHS_CHANGED)     │
│ - Parse node.code_text to AST:                         │
│   x = (x_train, x_test)                                │
│ - Find assignment with LHS=['x']                       │
│ - Create new target: Tuple(['x', 'y'])                │
│ - Update: assignment.targets = [new_target]           │
│ - Unparse: (x, y) = (x_train, x_test)                │
│ - Update: node.code_text = "..."                       │
└────────────────────┬────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────┐
│ STEP 5: Generate Skeleton                              │
│ - SkeletonGenerator.generate(ir)                       │
│ - For this node, status is GENERATED                   │
│ - Priority: Use node.code_text (from step 4)           │
│ - Output: (x, y) = (x_train, x_test)                  │
└─────────────────────────────────────────────────────────┘
```

### Critical Code Paths

#### Path 1: Skeleton Generation (Fast, No LLM)

**Where it's called:**
```python
# frontend → /skeleton endpoint → 
# AutoSync.on_spec_change() →
# IRSync.merge_and_transform() →
# skeleton_generator.generate()
```

**What should happen:**
1. Parse spec → new IR
2. Merge into session IR
3. Apply structural transforms
4. Generate skeleton from merged IR

**Current issue:** 
- Skeleton endpoint doesn't call `merge_and_transform()`
- Only merges, doesn't transform

#### Path 2: Full Sync with Generation (Slow, Uses LLM)

**Where it's called:**
```python
# frontend → /generate endpoint (on save) →
# AutoSync.on_spec_save() →
# IRSync.sync_spec_change() →
# [merge_and_transform, then generate_from_ir]
```

**Problem in test:**
```python
result = sync.sync_spec_change(spec_v1, spec_v2)
# This calls generate_from_ir() which needs LLM
# But with working structural transforms, it should only
# regenerate NEW incomplete nodes, not the x assignment
```

---

## Issue #1: Skeleton Endpoint Not Transforming

**File**: `backend/main.py` lines 137-198

**Current code**:
```python
@app.post("/skeleton")
async def skeleton_endpoint(request: AnalyzeRequest):
    session = get_or_create_session(request.session_id)
    
    new_ir = parse_semiformal(request.spec_code)
    
    if session.sync.ir:
        changes = session.sync.ir.merge_from_spec_update(new_ir)
        # ❌ MISSING: Apply structural transformations!
    else:
        session.sync.set_ir(new_ir)
    
    skeleton_code = generate_skeleton(session.sync.ir)
    
    # Return analysis + skeleton
    incomplete = session.sync.ir.get_incomplete_nodes()
    return {
        'skeleton_code': skeleton_code,
        'incomplete_nodes': [...],
        'message': '...'
    }
```

**What's missing:**
```python
# After merging, should apply transformations:
structural_changes = session.sync.differ.diff_specs(old_ir, new_ir)
if structural_changes:
    session.sync._apply_structural_transformations(structural_changes)
```

---

## Issue #2: Structural Transformation Not Invoked

**File**: `backend/ir_sync.py` lines 50-85

**Method `merge_and_transform()` defined but:**
- Not called from skeleton endpoint
- Only called from `sync_spec_change()` (full sync path)
- Therefore never used during continuous editing

**Need to call it in**:
- Skeleton endpoint (for instant transforms)
- OR directly in merge_from_spec_update

---

## Issue #3: Code Preservation in Skeleton

**File**: `backend/skeleton_generator.py` line 188

**Current code**:
```python
if node.status.value in ('generated', 'user_edited', 'needs_regen'):
    if node.code_text:
        return node.code_text  # ✅ CORRECT
```

**This is working correctly!**
- Problem is that `node.code_text` isn't being updated by transformer
- Transformer updates code in `_apply_structural_transformations()`
- But that's not called from skeleton endpoint

---

## Issue #4: AST Mapping Not Built in Skeleton Path

**File**: `backend/skeleton_generator.py` lines 116-170

**Current code**:
```python
def _build_ast_mapping(self, code: str, ir: ProgramIR) -> None:
    code_ast = ast.parse(code)
    for i, stmt in enumerate(code_ast.body):
        spec_node = self._find_spec_node_for_statement(stmt, ir, i)
        if spec_node:
            ast_path = f"body[{i}]"
            spec_node.code_ast_path = ast_path
            spec_node.code_ast = stmt
```

**Problem:**
- Mapping built AFTER skeleton generation
- But uses simple statement-level matching
- Doesn't match transformed code

**Why it breaks:**
1. Node added to skeleton with original code
2. Mapping tries to match it via `_find_spec_node_for_statement()`
3. Transformer modifies code AST but mapping already done
4. Mapping doesn't know about the transformation

---

## Issue #5: Test Design Issue

**File**: `test_lhs_change.py` line 68

**Problem:**
```python
result = sync.sync_spec_change(spec_v1, spec_v2)
# This always triggers LLM generation!
```

**Why:**
- `sync_spec_change()` calls `generate_from_ir()`
- `generate_from_ir()` calls DiffGenerator
- DiffGenerator tries to call OpenAI API

**Should be:**
```python
# Test structural transformation without LLM
sync.merge_and_transform(spec_v2)
skeleton = generate_skeleton(sync.ir)
# Verify transformation worked
```

---

## Recommended Fixes (Priority Order)

### Fix #1: Wire Structural Transforms in Skeleton Endpoint (HIGH PRIORITY)

**File**: `backend/main.py` `/skeleton` endpoint

```python
@app.post("/skeleton")
async def skeleton_endpoint(request: AnalyzeRequest):
    session = get_or_create_session(request.session_id)
    
    new_ir = parse_semiformal(request.spec_code)
    old_ir = session.sync.ir
    
    if old_ir:
        # 1. Detect structural changes
        structural_changes = session.sync.differ.diff_specs(old_ir, new_ir)
        
        # 2. Merge IR (preserves generated code)
        changes = old_ir.merge_from_spec_update(new_ir)
        
        # 3. Apply structural transformations
        if structural_changes:
            session.sync._apply_structural_transformations(structural_changes)
    else:
        session.sync.set_ir(new_ir)
    
    # Now generate skeleton with transformed code
    skeleton_code = generate_skeleton(session.sync.ir)
    
    incomplete = session.sync.ir.get_incomplete_nodes()
    
    return {
        'skeleton_code': skeleton_code,
        'incomplete_nodes': [node_to_dict(n) for n in incomplete],
        'message': f"Parsed spec: {len(incomplete)} incomplete elements"
    }
```

### Fix #2: Update AST Mapping After Transformation (HIGH PRIORITY)

**File**: `backend/skeleton_generator.py`

```python
def generate(self, ir: ProgramIR) -> str:
    lines = []
    
    # ... generate code ...
    
    result = "\n".join(lines)
    
    # Build AST mapping with transformed code
    self._build_ast_mapping(result, ir)
    
    return result

def _build_ast_mapping(self, code: str, ir: ProgramIR) -> None:
    # Current implementation works, but should account for
    # statements that may have been transformed
```

### Fix #3: Test Without LLM (MEDIUM PRIORITY)

**File**: `test_lhs_change.py`

```python
print("\n--- Step 3: Sync Spec Change ---")

# Use structural transformation path
sync.merge_and_transform(spec_v2)

# Don't call sync_spec_change (which triggers LLM)
# Instead manually regenerate skeleton
from backend.skeleton_generator import generate_skeleton
generated_code = generate_skeleton(sync.sync.ir)

print(f"Generated Code:\n{generated_code}")

# Verify transformation
if "(x, y) =" in generated_code and "(x_train, x_test)" in generated_code:
    print("✓ LHS transformation successful")
else:
    print("✗ LHS transformation failed")
```

### Fix #4: Implement Code → Spec Sync (LOWER PRIORITY)

**File**: `backend/ir_sync.py`

```python
# Complete the PUT path implementation
def on_code_change(self, new_code: str) -> SyncResult:
    # Detect what changed in code
    changes = self._detect_code_changes(self.last_code, new_code)
    
    # Extract intent via LLM
    for node_id, new_text in changes.items():
        node = self.ir.nodes.get(node_id)
        if node:
            # Use LLM to extract intent
            intent = llm_extract_intent(node, new_text)
            node.spec_text = intent
    
    return self.ir.apply_put(...)
```

---

## Summary of Mapping Components

| Component | Status | File | Lines | Issue |
|-----------|--------|------|-------|-------|
| IR Structure | ✅ Working | `ir.py` | 52-556 | None |
| Parser | ✅ Working | `ast_parser.py` | - | None |
| TreeDiffer | ✅ Working | `ast_operations.py` | 82-272 | None |
| StructuralTransformer | ✅ Working | `ast_operations.py` | 275-417 | Not called from skeleton |
| SkeletonGenerator | ✅ Working | `skeleton_generator.py` | 37-114 | Needs AST mapping update |
| merge_and_transform | ✅ Working | `ir_sync.py` | 50-85 | Not invoked from skeleton |
| Skeleton Endpoint | 🚧 Partial | `main.py` | 137-198 | Missing transformation call |
| DiffGenerator | ✅ Working | `diff_generator.py` | 88-166 | Requires LLM for any regen |

---

## Conclusion

The bidirectional synchronization system is architecturally sound. The main issue is **integration**: the `merge_and_transform()` method that applies structural transformations is not being called from the skeleton endpoint during continuous editing.

**Quick fix**: Add 3-4 lines to the `/skeleton` endpoint to call `merge_and_transform()` after merging IR.

**Impact**: Once fixed, LHS changes (x → x,y) and signature changes will be handled instantly without LLM regeneration.
