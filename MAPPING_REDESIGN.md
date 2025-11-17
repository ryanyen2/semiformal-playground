# Redesigning Mapping Architecture

## Current Problems

1. **Code generation creates duplicates**
2. **Line-level mapping too coarse** - can't distinguish between tokens on same line
3. **NL phrases all map to same statement** instead of their specific generated parts
4. **No way to map to specific AST nodes** (e.g., `output` token vs entire `print(output, x)`)

## Proposed Solution: Comment-Anchored Fine-Grained Mapping

### Phase 1: Improve Code Generation with Anchors

Modify LLM prompts to include spec-line comments:

```python
# spec:1:load - Load the dataset
data = pd.read_csv('your_dataset.csv')

# spec:1:process - Process the dataset
processed_data = data.dropna()

# spec:1:result - Assign to result
result = processed_data
```

**Benefits:**
- Clear mapping from spec to code
- Can parse comments to find corresponding code
- Enables fine-grained NL phrase mapping

### Phase 2: AST-Level Mapping (Not Line-Level)

Instead of:
```python
mapping = (node_id, line_number, code_snippet)
```

Use:
```python
mapping = (node_id, ast_node, line, col_start, col_end)
```

**For NL phrase "load":**
```python
# Maps to the Call node: pd.read_csv(...)
ast_node = ast.Call(func=ast.Attribute(value=ast.Name('pd'), attr='read_csv'))
line = 18
col_start = 7  # start of "pd.read_csv"
col_end = 34   # end of entire call
```

**For identifier "output" in print(output, x):**
```python
# Maps to the Name node 'output', not the entire Call
ast_node = ast.Name(id='output')
line = 29
col_start = 6   # start of "output"
col_end = 12    # end of "output"
```

### Phase 3: Comment-Based Code Slicing

Parse generated code for spec comments:

```python
def extract_spec_anchors(generated_code):
    """
    Find all spec comments and their corresponding code blocks.

    Returns:
        {
            'spec:1:load': (line_start, line_end, ast_nodes),
            'spec:1:process': (line_start, line_end, ast_nodes),
            ...
        }
    """
```

### Phase 4: NL Phrase → Code Fragment Mapping

Use anchors + semantic matching:

```python
def map_nl_phrase_to_code(nl_phrase, spec_line, generated_code, anchors):
    """
    Map a single NL phrase to its corresponding code.

    For "load" in spec line 1:
    1. Find anchor comment "spec:1:load"
    2. Extract code in that block
    3. Return specific AST node (pd.read_csv call)

    For "dataset":
    1. Find anchor comment "spec:1:load" (same block as "load")
    2. Within that block, find the dataset reference
    3. Return AST node for the string literal 'your_dataset.csv'
    """
```

### Phase 5: Deduplication Post-Processing

Before returning generated code:

```python
def deduplicate_generated_code(code):
    """
    Remove duplicate imports, duplicate statements.

    Strategy:
    1. Parse AST
    2. Track seen imports, seen statements
    3. Remove exact duplicates
    4. Preserve only first occurrence
    """
```

## Implementation Plan

### Step 1: Modify LLM Prompts
- Add instruction to include spec-line comments
- Format: `# spec:{line}:{keyword} - {description}`

### Step 2: Create Fine-Grained Mapper
- Parse spec comments from generated code
- Build AST and traverse to find specific nodes
- Map NL phrases to AST nodes (not lines)
- Store (line, col_start, col_end) for each mapping

### Step 3: Deduplication
- Post-process generated code to remove duplicates
- Keep mappings in sync during deduplication

### Step 4: Update Mapping Data Structure
```python
@dataclass
class FineGrainedMapping:
    node_id: str
    ast_node: ast.AST  # Specific AST node
    line: int
    col_start: int
    col_end: int
    code_text: str  # Just this node's text
    confidence: float
```

## Testing Strategy

Test with your example:

**Input:**
```
result = load dataset and process it
output = transform(result)
x, y = {split data into train and test}
print(output, x)
```

**Expected Mappings:**

```python
Node 0 (result) → line 23, col 0-6, "result"
Node 1 (load) → line 18, col 7-34, "pd.read_csv('your_dataset.csv')"
Node 2 (dataset) → line 18, col 20-33, "'your_dataset.csv'"
Node 3 (and) → <no specific code, structural>
Node 4 (process it) → line 21, col 18-30, "data.dropna()"
Node 5 (output) → line 25, col 0-6, "output"
Node 6 (result ref) → line 25, col 19-25, "result"
Node 7 (transform) → line 25, col 9-25, "transform(result)"
...
Node 11 (output ref in print) → line 29, col 6-12, "output"
Node 12 (x ref in print) → line 29, col 14-15, "x"
Node 13 (print call) → line 29, col 0-16, "print(output, x)"
```

This gives us:
- ✅ Fine-grained mapping (specific tokens)
- ✅ Different NL phrases map to different code
- ✅ References map to specific identifiers
- ✅ Can distinguish between tokens on same line
