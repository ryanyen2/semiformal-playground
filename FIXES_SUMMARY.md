# Bidirectional Programming Fixes Summary

## Overview
Fixed two critical issues in the bidirectional programming system:
1. Parser incorrectly recognizing incomplete vs complete Python
2. Mapping not maintained between left (spec) and right (code) after generation

## Issue 1: Parser Recognition of Incomplete vs Complete Python

### Problem
- `print` was incorrectly marked as incomplete (it's a builtin)
- `process_data()` and `transform()` calls were NOT recognized as incomplete (they reference undefined functions)
- Parser didn't distinguish between defined-but-incomplete functions and truly undefined functions

### Root Cause
The parser's `_is_nl_expression` method was too simplistic and didn't check:
1. If names are Python builtins
2. If function calls reference undefined/incomplete functions
3. The difference between natural language and valid Python syntax with undefined references

### Solution
**File: `backend/ast_parser.py`**

1. **Improved `_is_nl_expression()` (lines 654-696)**:
   - First tries to parse as Python expression
   - If it parses, it's NOT natural language (even if references are undefined)
   - Only marks as NL if it has NL keywords and multiple words

2. **Added `_has_undefined_or_incomplete_references()` (lines 641-685)**:
   - Checks if AST node calls undefined functions
   - Checks if AST node calls functions that are defined but incomplete (have `...`)
   - Properly handles Python builtins
   - Key insight: If a node calls an incomplete function, it should also be incomplete

3. **Added `_check_rhs_for_undefined_funcs()` (lines 620-639)**:
   - Used in line-by-line parsing where we don't have AST
   - Parses RHS as expression and uses AST-based checker

4. **Updated builtin checking** (lines 392-433, 541-567):
   - Uses `import builtins; builtin_names = set(dir(builtins))` 
   - Properly filters out builtins like `print`

5. **Applied checks in both parsing paths**:
   - AST-based parsing (`_build_ir_from_ast`)
   - Line-by-line parsing (`_parse_incomplete_code`)

### Results
- ✅ `print(...)` no longer creates a function_call node (recognized as builtin)
- ✅ `result = process_data(raw_input)` marked as INCOMPLETE (undefined function)
- ✅ `output = transform(x)` marked as INCOMPLETE (undefined function)  
- ✅ `x = split dataset into training and test sets` marked as INCOMPLETE (natural language)

## Issue 2: Mapping Not Maintained After Generation

### Problem
When user edits spec (left) after generation, the parser would force Python code (right) back to placeholder version. The generated code was being lost.

### Root Causes

**Cause 1: Session IR Not Used**
The `/skeleton` endpoint was creating a fresh IR each time, losing all generated code and status information from previous generation.

**Cause 2: Enum Identity Issue**
The skeleton generator was using enum identity comparison (`node.status in (NodeStatus.GENERATED, ...)`) which failed when enums were imported from different paths (`from ir import` vs `from backend.ir import`).

### Solution

**File: `backend/main.py` (lines 137-198)**

Updated `/skeleton` endpoint to:
1. Get or create session using `get_or_create_session()`
2. Parse new spec to get new IR
3. **Merge** new IR into existing session IR using `ir.merge_from_spec_update()`
4. Generate skeleton from merged IR (preserves generated code)

**File: `backend/skeleton_generator.py` (lines 29-75, 90-105)**

1. **Track code locations** (lines 47-73):
   - Added `current_line` tracking
   - Set `node.code_location` for bidirectional mapping
   - This maintains the correspondence between spec lines and code lines

2. **Fixed enum comparison** (lines 92-95):
   - Changed from `node.status in (NodeStatus.GENERATED, ...)` 
   - To `node.status.value in ('generated', 'user_edited', 'needs_regen')`
   - Uses value comparison to avoid enum identity issues

**File: `backend/diff_generator.py` (lines 142-162)**

Added code location tracking when applying implementations:
- Finds line where implementation appears
- Sets `node.code_location` for bidirectional mapping

### Results
- ✅ Session IR is maintained across spec edits
- ✅ Generated code is preserved when spec changes
- ✅ Skeleton shows generated code (not stub) for GENERATED nodes
- ✅ Mapping between left (spec) and right (code) is maintained

## Key Insights for Bidirectional Programming

### 1. Dependency Propagation
If a node calls an incomplete function, the calling node should also be incomplete. This is a form of "incompleteness propagation" that maintains consistency.

### 2. Stateful Sessions
Bidirectional programming requires maintaining state across edits:
- Session IR preserves generated code
- Status tracking (INCOMPLETE → GENERATED → NEEDS_REGEN)
- Merge operations preserve code while updating signatures

### 3. Bidirectional Mapping
Must maintain correspondence between source (left) and view (right):
- `spec_location`: where in spec this node appears
- `code_location`: where in generated code this node appears
- These enable bidirectional transformations

### 4. Get/Put Lens Laws
The system implements lens-like behavior:
- **Get**: spec → code (generation)
- **Put**: code → spec (sync back)
- Merging preserves generated code while applying spec changes

## Files Modified

1. **backend/ast_parser.py**: Parser improvements for incomplete detection
2. **backend/main.py**: Session-based skeleton endpoint
3. **backend/skeleton_generator.py**: Fixed enum comparison, added code locations
4. **backend/diff_generator.py**: Added code location tracking

## Testing

All test cases now pass:
- ✅ Parser correctly identifies incomplete vs complete Python
- ✅ Builtins (like `print`) are not marked as incomplete
- ✅ Undefined function calls are marked as incomplete
- ✅ Generated code is preserved across spec edits
- ✅ Skeleton shows generated code (not placeholders)
- ✅ Bidirectional mapping is maintained

