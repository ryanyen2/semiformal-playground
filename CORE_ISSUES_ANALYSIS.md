# Core Issues Analysis - Comprehensive Test Results

## Test Results Summary

Ran 7 diverse test cases. Found **3 major issue categories** across all tests.

## Issue 1: NL PHRASE GRANULARITY (HIGH SEVERITY) ⚠️

### What's Happening
Multiple NL phrases mapping to **same location** instead of different code fragments.

**Example from "Simple assignment with NL":**
```
Semiformal: x = load data from file

Parser output:
- Node 0: identifier 'x'
- Node 1: nl_phrase 'load data'
- Node 2: nl_phrase 'from'
- Node 3: nl_phrase 'file'

Current mappings (WRONG):
- load data → line 1 col 0-1 'x'
- from → line 1 col 0-1 'x'
- file → line 1 col 0-1 'x'

All three NL phrases map to the SAME identifier!
```

### ROOT CAUSE

**Two separate problems:**

1. **Parser problem:** Over-granular NL parsing
   - "load data from file" should be 1 phrase, not 3
   - "from" is a preposition, not a separate operation
   - Parser splits on common words ("from", "and", "to")

2. **Mapper problem:** Sibling-based fallback too coarse
   - When NL phrase can't be matched semantically, falls back to sibling
   - All siblings on same line → same location
   - No attempt to map different phrases to different code

### NEEDED FIX

**Parser fix:**
- Improve phrase chunking - don't split on prepositions
- "load data from file" → single phrase
- "load data, clean it, and transform" → 3 phrases: "load data", "clean it", "transform"

**Mapper fix:**
- Even when using sibling fallback, try to distinguish between phrases
- "load" → look for loading-related code (read_csv, load, open)
- "file" → look for filename strings or file operations
- "data" → look for data variable assignments

## Issue 2: UNMAPPED NODES (MEDIUM SEVERITY)

### What's Happening
Several node types not being mapped at all.

**Example from "Function call with args":**
```
Unmapped nodes (3 total):
- function_def 'process'
- parameter 'x'
- parameter 'y'

Also unmapped in other tests:
- operator '*'
- literal '2', '10', '5'
- import 'pandas'
```

### ROOT CAUSE

Fine-grained mapper only handles subset of node types:
```python
# Currently handled:
- identifier (def and ref)
- function_call
- nl_phrase (semantic + sibling fallback)
- hole (semantic + sibling fallback)
- expr_stmt (sibling fallback)

# NOT handled:
- function_def ❌
- parameter ❌
- operator ❌
- literal ❌
- import ❌
```

### NEEDED FIX

Add handlers for all node types:

```python
def map_function_def(intent_node) -> ASTMapping:
    """Map function definition to FunctionDef AST node"""
    # Find FunctionDef node with matching name

def map_parameter(intent_node) -> ASTMapping:
    """Map parameter to arg node in function signature"""

def map_operator(intent_node) -> ASTMapping:
    """Map operator to BinOp/UnaryOp AST node"""

def map_literal(intent_node) -> ASTMapping:
    """Map literal to Constant AST node"""

def map_import(intent_node) -> ASTMapping:
    """Map import to Import/ImportFrom AST node"""
```

## Issue 3: DUPLICATE REFERENCE MAPPING (HIGH SEVERITY) ⚠️

### What's Happening
Multiple references to same variable mapping to WRONG locations.

**Example from "Reference same variable multiple times":**
```
Semiformal:
Line 1: x = 10
Line 2: y = x + 5
Line 3: z = x * 2
Line 4: print(x, y, z)

Parsed nodes:
- Node 3: identifier 'x' (ref, line 1) - in y = x + 5
- Node 7: identifier 'x' (ref, line 2) - in z = x * 2
- Node 10: identifier 'x' (ref, line 3) - in print(x, y, z)

Current mappings (WRONG):
- Node 3 (x in line 2) → line 2 col 4-5 ✓ CORRECT
- Node 7 (x in line 3) → line 2 col 4-5 ❌ WRONG! Should be line 3
- Node 10 (x in print) → line 3 col 4-5 ❌ WRONG! Should be line 4

All x references after first one map to line 2!
```

### ROOT CAUSE

Reference scoring algorithm picks first match:

```python
# Current algorithm:
score = 100
+ 50 if main code (line >= 15)
- 50 if function body
- distance * 2 from expected line

# Problem: With same scoring, picks FIRST match (lowest line number)
# All x references have same score, so all pick line 2
```

### NEEDED FIX

**Much stronger weight on line distance:**

```python
score = 100
+ 50 if main code
- 50 if function body
- distance * 10  # ← Changed from * 2 to * 10

# Now:
# Node 3 (expected line 1, actual line 2): score = 100 - 10 = 90
# Node 7 (expected line 2, actual line 2): score = 100 - 0 = 100 ← Best!
# Node 7 (expected line 2, actual line 3): score = 100 - 10 = 90

# Each reference now picks its CLOSEST match!
```

**Even better: Use expected line as primary signal:**

```python
# Find all candidate matches
candidates = find_all_name_nodes(name)

# Separate by distance buckets
exact_line = [c for c in candidates if c.line == expected_line]
close_lines = [c for c in candidates if abs(c.line - expected_line) <= 2]
far_lines = [c for c in candidates if abs(c.line - expected_line) > 2]

# Pick from buckets in order
if exact_line:
    return exact_line[0]  # Prefer exact line match
elif close_lines:
    return min(close_lines, key=lambda c: abs(c.line - expected_line))
else:
    return min(far_lines, key=lambda c: abs(c.line - expected_line))
```

## Issue 4: CODE GENERATION QUALITY

### What's Happening
LLM generated code has duplicates:

```python
# Generated code has:
Line 2: """TODO: Implement this function."""
Line 6: """TODO: Implement this function."""  # ← Duplicate

# Also generates invalid Python:
def df.dropna():  # ← Invalid! Can't have . in function name
```

### ROOT CAUSE

1. **Duplication:** No post-processing to remove duplicates
2. **Invalid syntax:** Trying to create function defs for method calls

### NEEDED FIX

1. **Deduplication:** Already created `code_deduplicator.py` - just needs integration
2. **Method call detection:** Don't generate function defs for `obj.method()` patterns

## Summary: Core Fixes Needed

### Priority 1 (Critical):
1. **Fix reference mapping** - Stronger line distance weighting
2. **Fix NL phrase parser** - Better chunking, don't split on prepositions

### Priority 2 (Important):
3. **Add missing node type handlers** - function_def, parameter, operator, literal, import
4. **Integrate code deduplicator** - Remove duplicate imports/statements

### Priority 3 (Nice to have):
5. **Better NL semantic mapping** - Different phrases → different code
6. **Method call detection** - Don't generate defs for `obj.method()`

## Architectural Insight

The fundamental issue is **mapping granularity mismatch**:

- **Parser** creates many fine-grained nodes (load, data, from, file)
- **LLM** generates coarse code blocks (single read_csv call)
- **Mapper** tries to bridge the gap but fails

**Two possible solutions:**

### Option A: Coarser parsing
- Parse "load data from file" as single phrase
- Fewer nodes, easier 1:1 mapping
- **Pro:** Simpler mapping
- **Con:** Less detail, harder to do fine-grained edits

### Option B: Finer code generation
- Ask LLM to generate with comments marking each part:
```python
# load:
data = pd.read_csv(
    # file:
    'your_dataset.csv'
)
```
- **Pro:** Can map granularly
- **Con:** More complex generation, comments might be noise

### Option C: Hierarchical mapping (BEST)
- Map at multiple granularities:
  - Coarse: "load data from file" → entire `pd.read_csv(...)` call
  - Fine: "load" → `pd.read_csv` function
  - Fine: "file" → `'your_dataset.csv'` argument
- **Pro:** Flexible, supports both coarse and fine edits
- **Con:** More complex data structure

**Recommendation:** Option C - implement hierarchical mapping with parent/child relationships.
