# Fixing Bidirectional Mapping Issues

## Problems Identified

### 1. **Line/Column Mapping is Broken**
- Current `generator.py` increments `current_line` inconsistently
- Mappings created with incorrect line_start/line_end
- After generation, line numbers don't match between IR and AST

### 2. **Direct Edits Trigger LLM**
- Example: `print(output)` → `print(output, x)` triggers LLM instead of direct AST edit
- Root cause: Edit routing only checks `edit.type`, not actual node completeness
- Should be: Check if nodes involved are complete Python → direct edit

### 3. **No Clear Distinction Between Node Types**
- Need to distinguish:
  - **Complete Python** (direct edit): `print(x)`, `x = 5`, function calls to defined functions
  - **Incomplete Python** (split mapping): Function call without definition
  - **NL Expression** (LLM only): "load and preprocess data"

---

## Solution Architecture

### Phase 1: Fix Line/Column Mapping

**Problem:** `current_line` tracking is broken in generator.

**Fix:**
```python
def generate_with_mapping(self, nodes: List[IntentNode]):
    generated_lines = []
    mappings = []
    line_mappings = {}  # IR line → generated lines mapping

    for line_num in sorted(lines_dict.keys()):
        start_generated_line = len(generated_lines)

        # Generate code for this line
        code = self._generate_line(line_nodes)
        code_lines = code.split('\n')
        generated_lines.extend(code_lines)

        end_generated_line = len(generated_lines) - 1

        # Create accurate mapping
        line_mappings[line_num] = (start_generated_line, end_generated_line)

        # Create node mappings with CORRECT lines
        for node in line_nodes:
            mappings.append(Mapping(
                node_id=node.id,
                slices=[CodeSlice(
                    code=code,
                    line_start=start_generated_line,  # ← ACCURATE
                    line_end=end_generated_line,      # ← ACCURATE
                )],
                ...
            ))
```

### Phase 2: Node Classification System

**Create three node categories:**

```python
class NodeCompleteness(Enum):
    COMPLETE = "complete"        # Full Python: print(x), x=5, def foo():...
    INCOMPLETE = "incomplete"    # Partial: foo() without def, x={hint}
    NL = "nl"                    # Natural language: "load data"

def classify_node_completeness(node: IntentNode, all_nodes: List[IntentNode]):
    """Classify node by completeness."""

    # NL or hole → Incomplete/NL
    if node.type in ('nl_phrase', 'hole'):
        return NodeCompleteness.NL

    # Function call → Check if function is defined
    if node.type == 'function_call':
        func_name = node.content
        func_defined = any(
            n.type == 'function_def' and n.content == func_name
            for n in all_nodes
        )
        if func_defined:
            return NodeCompleteness.COMPLETE
        else:
            return NodeCompleteness.INCOMPLETE  # Call exists, no def

    # Function def → Check if body is complete
    if node.type == 'function_def':
        # Check metadata for body completeness
        has_body = node.metadata.get('has_body', False)
        if has_body:
            return NodeCompleteness.COMPLETE
        else:
            return NodeCompleteness.INCOMPLETE

    # Expression statements, identifiers, literals → Complete
    if node.type in ('expr_stmt', 'identifier', 'literal', 'operator'):
        return NodeCompleteness.COMPLETE

    return NodeCompleteness.INCOMPLETE
```

### Phase 3: Edit Decision Tree

**Determine action based on node completeness:**

```python
def decide_edit_action(
    edit: Edit,
    affected_nodes: List[IntentNode],
    all_nodes: List[IntentNode]
) -> str:
    """
    Decide whether to use direct edit, partial LLM, or full LLM.

    Returns: 'direct', 'llm_partial', 'llm_full'
    """
    # Classify all affected nodes
    classifications = [
        classify_node_completeness(node, all_nodes)
        for node in affected_nodes
    ]

    # All complete → Direct edit
    if all(c == NodeCompleteness.COMPLETE for c in classifications):
        return 'direct'

    # Any NL → LLM on that part only
    if any(c == NodeCompleteness.NL for c in classifications):
        # Find NL nodes and regenerate only those
        return 'llm_partial'

    # Some incomplete → Hybrid approach
    if any(c == NodeCompleteness.INCOMPLETE for c in classifications):
        # E.g., function call edit (direct) + function body regen (LLM)
        return 'llm_partial'

    return 'llm_full'
```

### Phase 4: Split Mapping for Incomplete Python

**For incomplete Python (e.g., `result = process_data(input)` without `def process_data`):**

```python
@dataclass
class SplitMapping:
    """For incomplete Python: separate usage and definition mapping"""
    node_id: str

    # Usage mapping (the call site) - direct editable
    usage_slice: CodeSlice
    usage_method: str = 'direct'

    # Definition mapping (generated stub/body) - LLM controlled
    definition_slices: List[CodeSlice]
    definition_method: str = 'llm_generated'

# Example:
# IR: result = process_data(input)
# Generated:
#   def process_data(input):  ← definition_slices
#       raise NotImplementedError()
#
#   result = process_data(input)  ← usage_slice

# When user edits call to process_data(input, step=2):
# - Direct edit on usage_slice (add argument)
# - LLM regeneration on definition_slices (update function signature + body)
```

---

## Implementation Plan

### Step 1: Fix Generator Line Tracking

**File:** `backend/generator.py`

```python
def generate_with_mapping(self, nodes):
    generated_lines = []
    mappings = []

    # Group by line
    lines_dict = self._group_by_line(nodes)

    for line_num in sorted(lines_dict.keys()):
        line_nodes = lines_dict[line_num]

        # Track where this line starts in generated code
        gen_start = len(generated_lines)

        # Generate code
        code = self._generate_line(line_nodes)
        code_lines = code.split('\n') if '\n' in code else [code]
        generated_lines.extend(code_lines)

        # Track where it ends
        gen_end = len(generated_lines) - 1

        # Create mappings with ACCURATE line numbers
        for node in line_nodes:
            mappings.append(Mapping(
                node_id=node.id,
                slices=[CodeSlice(
                    code='\n'.join(code_lines),
                    line_start=gen_start,
                    line_end=gen_end,
                )],
                ...
            ))

    return '\n'.join(generated_lines), mappings
```

### Step 2: Add Node Completeness Classification

**File:** `backend/node_classifier.py` (create new)

```python
"""
Node completeness classification for edit routing.
"""

from enum import Enum
from typing import List
from parser import IntentNode

class NodeCompleteness(Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    NL = "nl"

def classify_completeness(
    node: IntentNode,
    all_nodes: List[IntentNode]
) -> NodeCompleteness:
    """Classify node completeness."""
    # Implementation as above
    ...

def get_affected_nodes(
    edit_location: str,
    edit_line: int,
    nodes: List[IntentNode]
) -> List[IntentNode]:
    """Find nodes affected by an edit."""
    # Match by line number or node ID
    affected = []
    for node in nodes:
        if node.span[0] <= edit_line <= node.span[1]:
            affected.append(node)
        if node.id == edit_location:
            affected.append(node)
    return affected
```

### Step 3: Update Edit Router

**File:** `backend/edit_router.py`

```python
from node_classifier import classify_completeness, get_affected_nodes, NodeCompleteness

class EditTranslator:
    def __init__(self, mappings, generator, nodes):
        self.mappings = {m.node_id: m for m in mappings}
        self.generator = generator
        self.nodes = nodes  # ← Store IR nodes for classification
        self.direct_ops = DirectEditOperations()

    def semiformal_to_python(self, edit, semiformal_code, python_code):
        # Find affected nodes
        affected_nodes = get_affected_nodes(
            edit.location,
            edit.line or 0,
            self.nodes
        )

        # Classify completeness
        classifications = [
            classify_completeness(node, self.nodes)
            for node in affected_nodes
        ]

        # Decision tree
        if all(c == NodeCompleteness.COMPLETE for c in classifications):
            # ALL nodes are complete Python → Direct edit
            return self._direct_edit(edit, python_code)

        elif any(c == NodeCompleteness.NL for c in classifications):
            # Some NL → Regenerate those parts only
            nl_nodes = [
                n for n, c in zip(affected_nodes, classifications)
                if c == NodeCompleteness.NL
            ]
            return self._regenerate_partial(nl_nodes, semiformal_code, python_code)

        elif any(c == NodeCompleteness.INCOMPLETE for c in classifications):
            # Incomplete Python → Hybrid approach
            return self._handle_incomplete(edit, affected_nodes, python_code)

        else:
            # Fallback: regenerate
            return self._llm_regenerate_full(edit, semiformal_code, python_code)
```

### Step 4: Implement Direct Edit Detection

**Specific case: `print(output)` → `print(output, x)`**

```python
def _direct_edit(self, edit: Edit, python_code: str) -> EditResult:
    """Handle direct edits on complete Python."""

    # Detect edit type from diff
    if self._is_function_arg_add(edit):
        # Adding argument to function call
        return self.direct_ops.add_function_argument(
            python_code,
            edit.line,
            edit.metadata.get('function_name', ''),
            edit.metadata.get('new_arg', '')
        )

    elif self._is_function_arg_modify(edit):
        # Modifying existing argument
        return self.direct_ops.modify_argument(
            python_code,
            edit.line,
            edit.metadata.get('arg_index', 0),
            edit.content
        )

    # ... other direct edit types
```

---

## Example Scenarios

### Scenario 1: Direct Edit (Currently Broken)

**Input:**
```python
print(output)
```

**User Edit:**
```python
print(output, x)
```

**Current Behavior:** Triggers LLM ❌

**Fixed Behavior:**
1. Parse both versions
2. Find affected nodes: `print` call
3. Classify: `NodeCompleteness.COMPLETE` (builtin function)
4. Decision: `'direct'`
5. Action: Direct AST edit adding argument
6. Result: No LLM call ✅

### Scenario 2: Incomplete Python

**Input:**
```python
result = process_data(input)
```

**No `def process_data` exists**

**Mapping:**
```python
SplitMapping(
    node_id="node_3_process_data_call",
    usage_slice=CodeSlice(
        code="result = process_data(input)",
        line_start=5,
        line_end=5
    ),
    definition_slices=[CodeSlice(
        code="def process_data(input):\n    raise NotImplementedError()",
        line_start=0,
        line_end=1
    )]
)
```

**User Edit:** `result = process_data(input, step=2)`

**Action:**
1. Classify: `NodeCompleteness.INCOMPLETE` (function call without def)
2. Decision: `'llm_partial'`
3. Actions:
   - Direct edit on usage_slice: Add `step=2` argument
   - LLM regeneration on definition_slices: Update function signature and body
4. Result: Hybrid approach ✅

### Scenario 3: NL Expression

**Input:**
```python
data = load and preprocess the dataset
```

**Mapping:**
```python
Mapping(
    node_id="node_1_load_preprocess",
    slices=[CodeSlice(
        code="data = None  # TODO: Implement",
        line_start=0,
        line_end=0
    )],
    generation_method='placeholder'
)
```

**User Edit:** `data = load and clean the dataset`

**Action:**
1. Classify: `NodeCompleteness.NL`
2. Decision: `'llm_partial'`
3. Action: Regenerate only this NL expression → LLM
4. Result: Targeted regeneration ✅

---

## Testing Strategy

Create tests for each scenario:

```python
def test_direct_edit_print():
    """Test: print(x) → print(x, y) should be direct edit"""
    code_v1 = "print(output)"
    code_v2 = "print(output, x)"

    # Should NOT trigger LLM
    edit = detect_edit(code_v1, code_v2)
    action = decide_edit_action(edit, nodes, all_nodes)

    assert action == 'direct'

def test_incomplete_python():
    """Test: Function call without def should split mapping"""
    code = "result = process_data(input)"

    nodes = parse_semiformal(code)
    mapping = create_mapping(nodes, generated_code)

    assert isinstance(mapping, SplitMapping)
    assert mapping.usage_method == 'direct'
    assert mapping.definition_method == 'llm_generated'

def test_nl_expression():
    """Test: NL should trigger partial LLM"""
    code_v1 = "data = load and preprocess dataset"
    code_v2 = "data = load and clean dataset"

    edit = detect_edit(code_v1, code_v2)
    action = decide_edit_action(edit, nodes, all_nodes)

    assert action == 'llm_partial'
```

---

## Next Steps

1. ✅ Fix line/col tracking in generator.py
2. ✅ Add node completeness classification
3. ✅ Update edit router with decision tree
4. ✅ Implement split mapping for incomplete Python
5. ✅ Add direct edit detection for common cases
6. ✅ Test with real scenarios
7. ✅ Verify no LLM calls for direct edits

Expected outcome: **True bidirectional programming** where simple edits are instant (direct AST manipulation) and only semantic changes trigger LLM.
