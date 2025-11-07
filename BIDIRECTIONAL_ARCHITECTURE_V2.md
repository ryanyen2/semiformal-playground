# Bidirectional Programming Architecture V2

## Overview

This document describes the new bidirectional programming architecture where the **right side (Python code) is always a complete, executable program**, and the **left side (spec) is a projection/view** of the complete code.

## Key Principles

1. **Complete Programs on Right**
   - Right side must always be valid, executable Python
   - Undefined functions get stubs generated automatically
   - Complete Python statements (like `print`) are copied directly

2. **Spec as Projection**
   - Left side is a simplified view of the complete program
   - User edits on left should directly transform right (structural sync)
   - Only semantic changes require LLM regeneration

3. **AST-Level Mapping**
   - Each IR node maps to specific AST nodes in generated code
   - Maintains bidirectional correspondence for sync operations
   - Enables structural transformations without LLM

## Architecture Changes

### Phase 1: Complete Program Generation ✅

**Status**: Implemented

**Changes**:
1. **Skeleton Generator** (`backend/skeleton_generator.py`)
   - Generates stubs for all undefined functions (at top of file)
   - Copies complete Python statements directly
   - Preserves function call assignments as-is
   - Creates placeholders for natural language

2. **Parser** (`backend/ast_parser.py`)
   - Creates STATEMENT nodes for complete Python (e.g., `print(...)`)
   - Creates FUNCTION_CALL nodes for undefined functions
   - Extracts function calls from assignments for stub generation
   - Handles both AST-based and line-by-line parsing

**Results**:
```python
# Left (Spec):
result = process_data(raw_input)
x = split dataset into training and test sets
print(result, x)

# Right (Complete Program):
def process_data(*args, **kwargs):
    """TODO: Implement process_data"""
    raise NotImplementedError("process_data needs implementation")

result = process_data(raw_input)
x = ...  # split dataset into training and test sets
print(result, x)
```

### Phase 2: AST-Level Mapping (Pending)

**Goal**: Map IR nodes to specific AST nodes in generated code

**Implementation Plan**:
1. Add `code_ast_id` to IRNode
2. Track correspondence during skeleton generation
3. Update mapping after LLM generation
4. Use mapping for structural transformations

### Phase 3: Structural Transformations (Pending)

**Goal**: Handle certain edits without LLM regeneration

**Transformations to Support**:

1. **Function Signature Changes**
   ```
   Left: result = process_data(raw_input, methods)
   Right: Update function signature, keep body
   ```

2. **LHS Assignment Changes**
   ```
   Left: x, y = split dataset...
   Right: x, y = train_test_split(...)  # Update LHS only
   ```

3. **Function Call Argument Changes**
   ```
   Left: print(result, x, outputs)
   Right: print(result, x, outputs)  # Direct copy
   ```

### Phase 4: Smart Sync (Pending)

**Goal**: Distinguish structural vs semantic changes

**Strategy**:
- **Structural changes**: Handled by AST transformation
  - Signature changes
  - LHS changes
  - Argument reordering
  
- **Semantic changes**: Require LLM regeneration
  - Logic changes
  - New functionality
  - Algorithm changes

## IR Node Types

### Current Types

1. **FUNCTION_DEF**: Function definitions (complete or incomplete)
2. **FUNCTION_CALL**: Calls to undefined functions (need stubs)
3. **VARIABLE_ASSIGN**: Variable assignments
4. **NL_EXPRESSION**: Natural language assignments
5. **STATEMENT**: Complete Python statements (e.g., print)
6. **MODULE**: Top-level module

### Node Status Flow

```
INCOMPLETE -> GENERATED -> USER_EDITED
         -> NEEDS_REGEN -> GENERATED
SYNCED (always complete Python)
```

## Mapping Strategy

### Spec to Code Mapping

Each IR node maintains:
- `spec_location`: Location in spec source
- `spec_ast`: AST node from spec
- `spec_text`: Text from spec
- `code_location`: Location in generated code
- `code_ast`: AST node in generated code (TODO)
- `code_text`: Generated code text

### Example Mapping

```python
# Spec node:
IRNode(
    id="variable_assign:result:2",
    spec_location=SourceLocation(line=2, col=0),
    spec_text="result = process_data(raw_input)",
    code_location=SourceLocation(line=5, col=0),
    code_text="result = process_data(raw_input)"
)

# Function stub node:
IRNode(
    id="function_call:process_data:2",
    spec_location=SourceLocation(line=2, col=9),
    spec_text="process_data(...)",
    code_location=SourceLocation(line=1, col=0),
    code_text="def process_data(*args, **kwargs):\n    ..."
)
```

## Workflow

### 1. User Edits Spec (Left)

```python
# Before:
result = process_data(raw_input)

# After:
result = process_data(raw_input, methods)
```

### 2. Parser Detects Change

- Identifies: signature change in function call
- Type: Structural transformation
- Action: Update function signature in stub

### 3. Skeleton Generator Applies Transformation

```python
# Before:
def process_data(*args, **kwargs):
    # existing implementation
    return clean_data(args[0])

result = process_data(raw_input)

# After (structural transform):
def process_data(raw_input, methods):
    # existing implementation preserved
    return clean_data(raw_input)

result = process_data(raw_input, methods)
```

### 4. Optional: LLM Refinement

User can trigger regeneration to:
- Adapt implementation to new signature
- Add logic for new parameters
- Refine the transformation

## Benefits

1. **Always Executable**: Right side is always valid Python
2. **Fast Feedback**: Structural transforms are instant
3. **Preserved Code**: Generated implementations aren't lost on edits
4. **Bidirectional**: Edits flow both ways through mapping
5. **Incremental**: Only regenerate what changed

## Implementation Status

### ✅ Completed
- Complete program generation
- Stub generation for undefined functions
- Statement copying (print, etc.)
- Natural language placeholders
- Session-based IR preservation

### 🚧 In Progress
- AST-level mapping
- Structural transformations
- Smart sync detection

### 📋 Planned
- Infer function signatures from call sites
- Multi-file support
- Type inference
- Dependency tracking across files

## Next Steps

1. Implement AST-level mapping in IRNode
2. Add structural transformation for signature changes
3. Add structural transformation for LHS changes
4. Update ir_sync to distinguish structural vs semantic changes
5. Test with real-world examples

