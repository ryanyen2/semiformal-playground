# Robust Bidirectional Mapping Algorithm Design

## Overview

This document describes a comprehensive mapping algorithm for robust bidirectional synchronization between semiformal specifications and Python code. The algorithm addresses:

1. **Granular node-to-AST mapping**: Every IR node maps to specific Python AST subtrees
2. **Edit classification**: Different edit types trigger different actions
3. **Smart action dispatch**: Determine when to use direct edits vs LLM generation
4. **Underspecification handling**: Track and surface unmapped Python code

## 1. Node Classification System

### 1.1 Three Categories of IR Nodes

Every IR node is classified into one of three categories based on its completeness and mappability:

#### Category A: Direct Python (DIRECT_MAPPING)
**Characteristics:**
- Valid Python syntax
- All referenced entities are defined (built-ins, previously declared vars/funcs)
- Can be directly executed or are function calls with declarations elsewhere

**Examples:**
```python
print(result, x)              # Built-in function call
x = 5                          # Simple assignment
result = process_data(input)  # Function call (if process_data declared)
```

**Mapping:**
- 1:1 mapping to Python AST node
- Direct edits can be applied without LLM
- Changes propagate immediately

**Edit Actions:**
- **Structural changes** (e.g., x → x,y): Apply AST transformation
- **Value changes** (e.g., x = 5 → x = 10): Direct text replacement
- **Signature changes**: Update AST, may trigger dependent regeneration

---

#### Category B: Incomplete Python (HYBRID_MAPPING)
**Characteristics:**
- Python syntax structure present
- Contains undefined references or incomplete implementations
- Has a "shape" that can be mapped, but "content" needs generation

**Examples:**
```python
result = process_data(raw_input)  # Call exists, but no definition
x = ...                           # Variable with placeholder value
def transform(data):              # Function signature but no body
    ...
```

**Mapping:**
- IR node maps to:
  - **Call site/usage**: 1:1 AST node (the expression statement)
  - **Definition/implementation**: Maps to generated code (function body, value)
- Two-part mapping: structure + generated content

**Edit Actions:**
- **Call site edits** (args, LHS): Apply AST transformation (no LLM)
- **Signature edits**: Update signature AST, trigger body regeneration
- **Context changes**: Trigger regeneration of implementation only

**Key Insight:**
For `result = process_data(raw_input)`:
- The *call expression* is concrete → direct edit
- The *function body* is missing → LLM generation
- When user edits `process_data(raw_input, step=2)`, update call directly
- Then trigger regeneration of `process_data` function body with new context

---

#### Category C: Natural Language (NL_MAPPING)
**Characteristics:**
- Natural language description
- No direct Python syntax
- Represents intent, not implementation

**Examples:**
```python
x = load dataset and preprocess       # Pure NL
output = split data into train/test  # NL description
```

**Mapping:**
- IR node maps to generated Python code subtree
- Mapping is **fuzzy** and **many-to-many**:
  - One NL phrase might generate multiple statements
  - Multiple NL phrases might map to single function call
- Mapping includes **semantic anchors** (variable names, key terms)

**Edit Actions:**
- **Any edit**: Trigger regeneration of entire mapped subtree
- **Fuzzy matching**: Use semantic similarity to determine scope
- **Boundary detection**: Identify which generated code belongs to this NL node

**Challenges:**
- "load dataset and preprocess" might generate:
  ```python
  dataset = load_dataset('data.csv')
  dataset_cleaned = preprocess(dataset)
  ```
- If user changes to "load and normalize dataset", need to regenerate entire subtree
- Must detect boundaries to avoid regenerating neighboring code

---

## 2. Enhanced IR Node Structure

Extend `IRNode` to include mapping information:

```python
@dataclass
class IRNode:
    # ... existing fields ...

    # Enhanced mapping information
    mapping_category: MappingCategory  # DIRECT, HYBRID, NL

    # Python AST mapping (can be multiple nodes)
    code_ast_nodes: List[ast.AST]  # All AST nodes this IR node maps to
    code_ast_paths: List[str]       # Paths to each AST node

    # For HYBRID: distinguish usage vs definition
    usage_ast_nodes: List[ast.AST]      # Call sites, variable refs
    definition_ast_nodes: List[ast.AST] # Function bodies, implementations

    # For NL: track generated code boundaries
    generated_code_span: Optional[Tuple[int, int]]  # (start_line, end_line)
    semantic_anchors: List[str]  # Key terms for fuzzy matching

    # Underspecification tracking
    is_underspecified: bool  # True if generated code exceeds spec
    underspec_reason: str    # Why this is underspecified

    # Edit tracking
    last_edit_type: Optional[str]  # Type of last edit
    requires_regeneration: bool     # Flag for LLM regeneration
```

---

## 3. Bidirectional Mapping Structure

### 3.1 IR → Python AST Mapping

**Forward Mapping (`IRToPythonMapper`):**

```python
class IRToPythonMapping:
    """Maintains mapping from IR nodes to Python AST."""

    # Primary mapping: IR node ID → list of Python AST paths
    ir_to_ast: Dict[str, List[str]]  # node_id → ["body[0]", "body[1].body[0]"]

    # Category-specific mappings
    direct_mappings: Dict[str, str]      # node_id → single AST path
    hybrid_mappings: Dict[str, HybridMap]  # node_id → {usage: [...], definition: [...]}
    nl_mappings: Dict[str, NLMap]        # node_id → {subtree_roots: [...], span: (s, e)}

    # Underspecification tracking
    unmapped_ast_paths: Set[str]  # AST nodes without IR mapping
    underspec_nodes: Dict[str, List[str]]  # IR node → extra generated AST paths
```

### 3.2 Python AST → IR Mapping

**Reverse Mapping (`PythonToIRMapper`):**

```python
class PythonToIRMapping:
    """Maintains mapping from Python AST to IR nodes."""

    # Primary reverse mapping: AST path → IR node ID
    ast_to_ir: Dict[str, str]  # "body[0]" → node_id

    # For generated code: track which IR node generated it
    generated_code_map: Dict[str, str]  # AST path → generating node_id

    # Ownership tracking (for multi-statement NL)
    ast_ownership: Dict[str, Set[str]]  # AST path → set of contributing node IDs
```

---

## 4. Mapping Algorithm

### 4.1 Building Initial Mapping

**Algorithm: `build_bidirectional_mapping(ir: ProgramIR, code_ast: ast.Module)`**

```
1. Initialize empty mappings

2. For each IR node in topological order:

   a. Classify node into DIRECT, HYBRID, or NL

   b. Based on category:

      DIRECT:
        - Find matching AST node by:
          * Line number (if available)
          * Signature matching (for functions)
          * Name matching (for variables)
        - Create 1:1 mapping
        - Mark AST node as mapped

      HYBRID:
        - Find usage AST nodes (call sites, references)
        - Find definition AST nodes (function bodies, values)
        - Create dual mapping
        - Mark both as mapped

      NL:
        - Use semantic anchors (variable names in spec)
        - Identify generated code span from line numbers
        - Extract all AST nodes in that span
        - Create many-to-many mapping
        - Mark all as mapped to this NL node

   c. Record mapping in both directions

3. Identify unmapped AST nodes:
   - Traverse code AST
   - For each node not in ast_to_ir mapping:
     * Mark as underspecified
     * Find nearest mapped node (for context)
     * Record for potential surfacing to user

4. Validate mapping consistency:
   - Check that all mapped AST paths are valid
   - Verify no conflicts in reverse mapping
   - Ensure coverage (minimize unmapped nodes)

5. Return IRToPythonMapping and PythonToIRMapping
```

### 4.2 Classification Algorithm

**Algorithm: `classify_node(node: IRNode) → MappingCategory`**

```
Classification decision tree:

1. Check if node is natural language:
   - If spec_text contains primarily NL (no Python keywords/operators)
   - If spec_ast is None or failed to parse
   → Return NL_MAPPING

2. Check if valid Python syntax:
   - If spec_ast is valid Python AST

   a. Check completeness:
      - For function calls:
        * Is the function defined in IR or builtins?
        * If YES → DIRECT_MAPPING
        * If NO → HYBRID_MAPPING (call is direct, body needs gen)

      - For assignments:
        * Is RHS a concrete value or built-in operation?
        * If YES → DIRECT_MAPPING
        * Is RHS ellipsis (...) or undefined reference?
        * If YES → HYBRID_MAPPING

      - For function definitions:
        * Does body contain only pass/... or undefined references?
        * If YES → HYBRID_MAPPING
        * If NO → DIRECT_MAPPING

3. Default:
   → NL_MAPPING (when in doubt, treat as natural language)
```

---

## 5. Edit Handling Matrix

### 5.1 Edit Classification

For each edit, classify into:

| Edit Type | Description | Example |
|-----------|-------------|---------|
| **STRUCTURAL** | LHS/RHS shape change | `x = ...` → `x, y = ...` |
| **SIGNATURE** | Function signature change | `def f(a):` → `def f(a, b):` |
| **VALUE** | Literal value change | `x = 5` → `x = 10` |
| **SEMANTIC** | NL content change | `load data` → `load and normalize data` |
| **ADDITION** | New node added | Adding new line |
| **REMOVAL** | Node removed | Deleting line |
| **REORDER** | Node moved | Line moved up/down |

### 5.2 Action Dispatch Matrix

Based on (node category, edit type) → action:

| Category | Edit Type | Action | Requires LLM? | Updates Mapping? |
|----------|-----------|--------|---------------|------------------|
| **DIRECT** | STRUCTURAL | AST transformation | ❌ No | ✅ Yes (update AST paths) |
| **DIRECT** | VALUE | Direct text replacement | ❌ No | ❌ No |
| **DIRECT** | SIGNATURE | Update signature + check deps | ❌ No | ✅ Yes |
| **DIRECT** | ADDITION | Insert new AST node | ❌ No | ✅ Yes |
| **DIRECT** | REMOVAL | Delete AST node | ❌ No | ✅ Yes |
| **DIRECT** | SEMANTIC | Re-classify, may → NL | ⚠️ Maybe | ✅ Yes |
| | | | | |
| **HYBRID** | STRUCTURAL (usage) | AST transformation on call | ❌ No | ✅ Yes (usage only) |
| **HYBRID** | STRUCTURAL (definition) | Regen function body | ✅ Yes | ✅ Yes (definition only) |
| **HYBRID** | SIGNATURE | Update sig + regen body | ✅ Yes | ✅ Yes (both) |
| **HYBRID** | VALUE | N/A (no direct values) | — | — |
| **HYBRID** | ADDITION | Insert call + regen definition | ✅ Yes | ✅ Yes |
| **HYBRID** | REMOVAL | Delete call + definition | ❌ No | ✅ Yes |
| **HYBRID** | SEMANTIC | Re-classify or regen | ✅ Yes | ✅ Yes |
| | | | | |
| **NL** | STRUCTURAL | Regen entire subtree | ✅ Yes | ✅ Yes (rebuild subtree map) |
| **NL** | SIGNATURE | Regen with new signature | ✅ Yes | ✅ Yes |
| **NL** | VALUE | Regen entire subtree | ✅ Yes | ✅ Yes |
| **NL** | SEMANTIC | Regen entire subtree | ✅ Yes | ✅ Yes |
| **NL** | ADDITION | Generate new subtree | ✅ Yes | ✅ Yes |
| **NL** | REMOVAL | Delete subtree | ❌ No | ✅ Yes |
| **NL** | REORDER | Update mapping, no regen | ❌ No | ✅ Yes |

### 5.3 Action Execution

**Algorithm: `execute_edit_action(node: IRNode, edit: EditInfo)`**

```python
def execute_edit_action(node: IRNode, edit: EditInfo, mapping: IRToPythonMapping):
    """Execute appropriate action based on node category and edit type."""

    category = node.mapping_category
    edit_type = edit.edit_type

    # Dispatch based on (category, edit_type)

    if category == MappingCategory.DIRECT:

        if edit_type == EditType.STRUCTURAL:
            # Apply AST transformation without LLM
            new_ast = apply_structural_transform(node, edit)
            update_code_ast(node, new_ast, mapping)
            node.requires_regeneration = False

        elif edit_type == EditType.VALUE:
            # Direct text replacement
            node.code_text = edit.new_value
            node.requires_regeneration = False

        elif edit_type == EditType.SIGNATURE:
            # Update signature in AST
            update_signature_ast(node, edit.new_signature, mapping)
            # Check if any dependents need regeneration
            for dep_id in node.used_by:
                dep_node = ir.nodes[dep_id]
                dep_node.requires_regeneration = True
            node.requires_regeneration = False

    elif category == MappingCategory.HYBRID:

        if edit_type == EditType.STRUCTURAL:
            # Usage-side change (e.g., function call arguments)
            if edit.affects_usage:
                # Direct AST transformation on call site
                new_call_ast = apply_structural_transform(node.usage_ast_nodes[0], edit)
                update_usage_ast(node, new_call_ast, mapping)

            # Definition-side change (e.g., function body shape)
            if edit.affects_definition:
                # Mark for regeneration
                node.requires_regeneration = True
                node.status = NodeStatus.NEEDS_REGEN

        elif edit_type == EditType.SIGNATURE:
            # Update call signatures (direct)
            update_signature_ast(node, edit.new_signature, mapping)
            # Mark definition for regeneration
            node.requires_regeneration = True
            node.status = NodeStatus.NEEDS_REGEN

    elif category == MappingCategory.NL:

        # Any edit to NL requires regeneration of entire subtree
        node.requires_regeneration = True
        node.status = NodeStatus.NEEDS_REGEN

        # Mark all AST nodes in subtree for regeneration
        for ast_path in mapping.ir_to_ast[node.id]:
            mark_subtree_for_regeneration(ast_path, mapping)

    # Update mapping
    mapping.update_after_edit(node, edit)
```

---

## 6. Tree Traversal and Slicing

### 6.1 AST Subtree Extraction

**Algorithm: `extract_subtree(code_ast: ast.Module, ir_node: IRNode) → List[ast.stmt]`**

For NL nodes, we need to extract the entire generated subtree:

```python
def extract_subtree(code_ast: ast.Module, ir_node: IRNode,
                     mapping: IRToPythonMapping) -> List[ast.stmt]:
    """Extract all AST statements generated for this IR node."""

    if ir_node.mapping_category == MappingCategory.NL:
        # Use generated code span
        start_line, end_line = ir_node.generated_code_span

        # Extract all statements in this span
        subtree = []
        for stmt in ast.walk(code_ast):
            if isinstance(stmt, ast.stmt):
                if start_line <= stmt.lineno <= end_line:
                    subtree.append(stmt)

        return subtree

    elif ir_node.mapping_category == MappingCategory.HYBRID:
        # Return both usage and definition nodes
        return ir_node.usage_ast_nodes + ir_node.definition_ast_nodes

    else:  # DIRECT
        # Return single mapped node
        return ir_node.code_ast_nodes
```

### 6.2 Subtree Slicing for Regeneration

**Algorithm: `slice_for_regeneration(ir: ProgramIR, changed_nodes: Set[str]) → List[IRNode]`**

Determine minimal set of nodes requiring LLM regeneration:

```python
def slice_for_regeneration(ir: ProgramIR, changed_nodes: Set[str]) -> List[IRNode]:
    """Compute minimal slice of nodes requiring regeneration."""

    needs_regen = set()

    # Start with explicitly changed nodes that require regeneration
    for node_id in changed_nodes:
        node = ir.nodes[node_id]
        if node.requires_regeneration:
            needs_regen.add(node_id)

    # Propagate through dependencies
    changed = True
    while changed:
        changed = False
        for node_id in list(needs_regen):
            node = ir.nodes[node_id]
            # Add dependents if they rely on this node
            for dep_id in node.used_by:
                if dep_id not in needs_regen:
                    dep_node = ir.nodes[dep_id]
                    # Only add if dependent is HYBRID or NL and uses signature
                    if dep_node.mapping_category != MappingCategory.DIRECT:
                        if depends_on_signature(dep_node, node):
                            needs_regen.add(dep_id)
                            changed = True

    # Return in topological order for generation
    return topological_sort([ir.nodes[nid] for nid in needs_regen])
```

---

## 7. Underspecification Handling

### 7.1 Detecting Underspecification

Underspecification occurs when:
1. Generated code contains more than specified (e.g., error handling added by LLM)
2. AST nodes exist without IR mapping
3. Helper functions generated but not specified

**Algorithm: `detect_underspecification(code_ast: ast.Module, mapping: PythonToIRMapping) → List[UnderspecNode]`**

```python
def detect_underspecification(code_ast: ast.Module,
                               mapping: PythonToIRMapping) -> List[UnderspecNode]:
    """Find code that doesn't map back to any spec."""

    underspec = []

    for path, node in enumerate_ast_paths(code_ast):
        # Check if this AST node is mapped to any IR node
        if path not in mapping.ast_to_ir:
            # Unmapped node - potential underspecification

            # Find context (nearest mapped parent)
            parent_path = get_parent_path(path)
            while parent_path and parent_path not in mapping.ast_to_ir:
                parent_path = get_parent_path(parent_path)

            context_node_id = mapping.ast_to_ir.get(parent_path)

            underspec.append(UnderspecNode(
                ast_path=path,
                ast_node=node,
                context_ir_node_id=context_node_id,
                reason="Generated code without spec correspondence"
            ))

    return underspec
```

### 7.2 Surfacing Underspecification

**Option 1: Mark in UI**
- Highlight underspecified code in gray or with indicator
- Show tooltip: "This code was generated but not directly specified"

**Option 2: Add to spec**
- Auto-generate spec comment: `# [generated] error handling`
- Allow user to promote to full spec or delete

**Option 3: Track separately**
- Maintain underspec registry
- Don't modify until user explicitly edits that code region

---

## 8. Mapping Update Strategy

### 8.1 When to Rebuild Mapping

| Event | Rebuild Strategy |
|-------|------------------|
| Initial parse | Full rebuild |
| DIRECT node structural edit | Incremental update (update single path) |
| HYBRID node signature edit | Incremental update (usage + definition) |
| NL node edit | Incremental update (regenerate subtree, update paths) |
| Node addition | Incremental insert |
| Node removal | Incremental delete |
| Multiple nodes changed | Batch incremental updates |
| Code → spec sync | Full rebuild (reverse direction) |

### 8.2 Incremental Update Algorithm

```python
def incremental_update_mapping(mapping: IRToPythonMapping,
                                node: IRNode,
                                edit: EditInfo):
    """Incrementally update mapping after edit."""

    if edit.edit_type == EditType.STRUCTURAL:
        # AST paths may have changed
        old_paths = mapping.ir_to_ast[node.id]
        new_paths = compute_new_paths(node, edit)

        # Update forward mapping
        mapping.ir_to_ast[node.id] = new_paths

        # Update reverse mapping
        for old_path in old_paths:
            if old_path in mapping.reverse.ast_to_ir:
                del mapping.reverse.ast_to_ir[old_path]
        for new_path in new_paths:
            mapping.reverse.ast_to_ir[new_path] = node.id

    elif edit.edit_type in (EditType.ADDITION, EditType.REMOVAL):
        # Paths after edit location shifted
        shift_amount = compute_shift(edit)
        update_paths_after_line(mapping, edit.line, shift_amount)
```

---

## 9. Example Scenarios

### Scenario 1: LHS Change (x → x,y)

**Initial:**
```python
Spec:  x = split dataset into training and test sets
Code:  x = (train_data, test_data)
```

**User edits spec:**
```python
Spec:  x, y = split dataset into training and test sets
```

**Mapping algorithm execution:**

1. **Parse**: Create new IR node with `metadata['lhs'] = ['x', 'y']`
2. **Classify**: Node is NL_MAPPING (natural language)
3. **Match**: Find old node at same line
4. **Detect edit**: STRUCTURAL change (LHS modified)
5. **Classify edit impact**:
   - NL node + STRUCTURAL edit → Requires regeneration
   - BUT: Check if generated code can be structurally transformed
6. **Action**: Since generated code is simple assignment with compatible structure:
   - Apply structural transform: `x = ...` → `(x, y) = ...`
   - Mark `requires_regeneration = False`
7. **Update mapping**: Update AST path for this assignment
8. **Result**: `(x, y) = (train_data, test_data)` [No LLM call!]

### Scenario 2: Function Call Argument Change

**Initial:**
```python
Spec:  result = process_data(raw_input)
Code:  result = process_data(raw_input)

       def process_data(raw_input):
           # ... generated implementation ...
```

**User edits spec:**
```python
Spec:  result = process_data(raw_input, normalize=True)
```

**Mapping algorithm execution:**

1. **Parse**: Update IR node with new call signature
2. **Classify**: Node is HYBRID_MAPPING (call is concrete, definition generated)
3. **Match**: Find same node (process_data call)
4. **Detect edit**: SIGNATURE change (new argument)
5. **Classify edit impact**:
   - HYBRID + SIGNATURE → Usage direct, definition regen
6. **Actions**:
   a. **Direct**: Update call site AST: `process_data(raw_input, normalize=True)`
   b. **Mark**: Function definition `requires_regeneration = True`
7. **Update mapping**: Call site path updated
8. **On save**: Regenerate only `process_data` function body with new signature

### Scenario 3: NL Content Change

**Initial:**
```python
Spec:  x = load dataset and preprocess
Code:  data_path = 'dataset.csv'
       raw_data = load_csv(data_path)
       x = preprocess_data(raw_data)
```

**User edits spec:**
```python
Spec:  x = load and normalize dataset
```

**Mapping algorithm execution:**

1. **Parse**: New IR node with different semantic content
2. **Classify**: Still NL_MAPPING
3. **Match**: Same line, same node
4. **Detect edit**: SEMANTIC change (NL content changed)
5. **Classify edit impact**:
   - NL + SEMANTIC → Full subtree regeneration required
6. **Identify subtree**: All generated code lines (3 statements in this case)
7. **Mark**: Entire subtree `requires_regeneration = True`
8. **On save**: Regenerate entire subtree (may produce different structure)
9. **Update mapping**: Rebuild mapping for this node's generated code span

---

## 10. Implementation Checklist

### Phase 1: Enhanced Classification
- [ ] Add `MappingCategory` enum
- [ ] Implement `classify_node()` algorithm
- [ ] Update `IRNode` with mapping fields
- [ ] Add classification during parsing

### Phase 2: Mapping Structures
- [ ] Implement `IRToPythonMapping` class
- [ ] Implement `PythonToIRMapping` class
- [ ] Create bidirectional consistency checks

### Phase 3: Mapping Algorithm
- [ ] Implement `build_bidirectional_mapping()`
- [ ] Add DIRECT node matching
- [ ] Add HYBRID node dual mapping
- [ ] Add NL subtree extraction
- [ ] Add underspecification detection

### Phase 4: Edit Classification
- [ ] Implement `EditType` enum
- [ ] Implement edit detection in TreeDiffer
- [ ] Add edit type classification

### Phase 5: Action Dispatch
- [ ] Implement action dispatch matrix
- [ ] Add handlers for each (category, edit_type) pair
- [ ] Implement regeneration slicing
- [ ] Add incremental mapping updates

### Phase 6: Integration
- [ ] Update `/skeleton` endpoint to use new mapping
- [ ] Update `merge_and_transform()` to use classification
- [ ] Add mapping to session state
- [ ] Update frontend to show mapping status

### Phase 7: Testing
- [ ] Test all node categories
- [ ] Test all edit types
- [ ] Test edge cases (reordering, complex edits)
- [ ] Performance testing on large files

---

## 11. Performance Considerations

### 11.1 Mapping Build Time

**Complexity:**
- Initial mapping: O(n × m) where n = IR nodes, m = AST nodes
- With indexing: O(n + m)

**Optimization:**
- Build line number index for AST nodes
- Use signature hashing for fast matching
- Cache mapping between requests

### 11.2 Incremental Updates

Most edits affect only 1-3 nodes:
- Single node update: O(1)
- Dependency propagation: O(d) where d = number of dependents
- Path shifting: O(k) where k = nodes after edit

**Target:** < 50ms for incremental update

### 11.3 Regeneration Slicing

Minimize LLM calls by computing minimal slice:
- Use dependency graph traversal
- Only include nodes that truly depend on changed content
- Batch multiple nodes into single LLM call when possible

---

## 12. Future Enhancements

### 12.1 Type Inference

Add type information to mapping:
- Infer types from context and usage
- Track type flow through program
- Use for better matching and validation

### 12.2 Semantic Similarity Matching

For NL nodes:
- Use embeddings to measure semantic similarity
- Better detect when NL edit is minor vs major
- Avoid regeneration for semantically equivalent edits

### 12.3 Multi-Granularity Mapping

Support mapping at multiple levels:
- Statement level (current)
- Expression level (finer)
- Block level (coarser)

Choose granularity based on node type and edit.

### 12.4 User-Guided Mapping

Allow user to:
- Manually adjust mapping for ambiguous cases
- Lock certain generated code from regeneration
- Annotate underspecified code with intent

---

## Conclusion

This robust mapping algorithm provides:

1. **Clear categorization** of nodes into DIRECT, HYBRID, NL
2. **Granular mapping** from IR to Python AST with proper tracking
3. **Smart action dispatch** based on (category, edit_type)
4. **Minimal LLM usage** by applying direct transforms when possible
5. **Underspecification handling** to surface unmapped code
6. **Efficient updates** through incremental mapping maintenance

The algorithm ensures that:
- Simple structural changes (x → x,y) don't require LLM
- Incomplete Python is handled with dual mapping (usage + definition)
- Natural language properly triggers regeneration
- All code is properly tracked and mapped
