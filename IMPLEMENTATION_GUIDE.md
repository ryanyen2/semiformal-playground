# Quick Implementation Guide

## TL;DR: The Key Insight

**Separate structural sync from semantic generation:**

- **Structural sync** (stubs, placeholders, comments) → Instant, no LLM
- **Semantic generation** (actual code) → Deferred, triggered on save or completion

## Critical Path Implementation

### 1. Skeleton Generation (Week 1 - PRIORITY 1)

**Goal**: When user types on left, Python updates instantly with structure

**What to build**:
```python
# backend/skeleton_generator.py (NEW FILE)
def generate_skeleton(ir: ProgramIR) -> str:
    """Generate Python skeleton from IR without LLM."""
    # For each node:
    # - SYNCED → copy as-is
    # - INCOMPLETE function → stub with ...
    # - INCOMPLETE variable → placeholder with comment
    # - PSEUDOCODE → commented NL
```

**API endpoint**:
```python
# backend/main.py (ADD)
@app.post("/generate-skeleton")
async def generate_skeleton_endpoint(request: AnalyzeRequest):
    ir = parse_semiformal(request.spec_code)
    skeleton = generate_skeleton(ir)
    return {'skeleton_code': skeleton}
```

**Frontend integration**:
```typescript
// frontend/src/index.ts (MODIFY)
async function performAnalysis() {
  // ... existing analysis ...
  
  // ADD: Generate and display skeleton
  const skeleton = await generateSkeleton(specCode)
  setEditorContent(codeEditor, skeleton)
}
```

### 2. Enhanced Node Classification (Week 1)

**Goal**: Correctly classify pseudocode vs incomplete Python

**What to build**:
```python
# backend/ast_parser.py (ENHANCE)
def _is_pseudocode(self, line: str) -> bool:
    pseudocode_patterns = [
        'for each', 'apply', 'where', 'when',
        'given', 'then', 'using'
    ]
    return any(p in line.lower() for p in pseudocode_patterns)

def _parse_incomplete_code(self, source: str):
    # ADD: Detect pseudocode nodes
    # CREATE: NodeType.PSEUDOCODE nodes
```

### 3. Improved Context for Generation (Week 2)

**Goal**: LLM sees full program context including usage patterns

**What to build**:
```python
# backend/diff_generator.py (ENHANCE)
def _build_program_context(self, ir: ProgramIR):
    context = {
        # ... existing ...
        'function_usage': self._analyze_usage(ir),
        'data_sources': self._find_data_sources(ir),
        'outputs': self._find_outputs(ir),
    }
    return context

def _analyze_usage(self, ir: ProgramIR):
    """Find how each function is called."""
    # Analyze call sites to infer requirements
```

### 4. Code Mapping (Week 2-3)

**Goal**: Track which Python lines correspond to which IR nodes

**What to build**:
```python
# backend/code_mapper.py (NEW FILE)
class CodeMapper:
    def embed_markers(self, code, ir) -> str:
        """Add invisible IR markers to Python code."""
    
    def extract_node_code(self, code, node_id) -> str:
        """Extract code for specific IR node."""
    
    def update_node_code(self, code, node_id, new_code) -> str:
        """Replace code for specific node."""
```

### 5. Code → Spec Abstraction (Week 4)

**Goal**: Extract high-level intent from Python

**What to build**:
```python
# backend/code_abstractor.py (NEW FILE)
class CodeAbstractor:
    def abstract_function(self, func_code) -> str:
        """Convert implementation to high-level spec."""
        # 1. Try docstring
        # 2. Fall back to LLM summarization
    
    def abstract_variable(self, var_name, expr, context) -> str:
        """Convert complex expression to NL."""
```

## Quick Wins (Implement These First)

### Win 1: Real-Time Stubs (2 hours)

```python
# backend/skeleton_generator.py
from ir import ProgramIR, NodeType, NodeStatus

def generate_skeleton(ir: ProgramIR) -> str:
    lines = []
    
    for node in sorted(ir.nodes.values(), key=lambda n: n.spec_location.line if n.spec_location else 0):
        if node.status == NodeStatus.SYNCED:
            lines.append(node.spec_text)
        elif node.node_type == NodeType.FUNCTION_DEF:
            lines.append(create_function_stub(node))
        elif node.node_type == NodeType.NL_EXPRESSION:
            lines.append(create_variable_placeholder(node))
        elif node.node_type == NodeType.PSEUDOCODE:
            lines.append(f"# PSEUDOCODE: {node.spec_text}")
        
        lines.append("")
    
    return "\n".join(lines)

def create_function_stub(node):
    # Extract params from AST or text
    if node.spec_ast:
        params = ', '.join([arg.arg for arg in node.spec_ast.args.args])
        return f"def {node.name}({params}):\n    \"\"\"TODO: Implement\"\"\"\n    ..."
    return f"def {node.name}():\n    ..."

def create_variable_placeholder(node):
    nl_desc = node.metadata.get('rhs', '')
    return f"{node.name} = ...  # {nl_desc}"
```

### Win 2: Pseudocode Detection (1 hour)

```python
# backend/ast_parser.py - add to _parse_incomplete_code()

PSEUDOCODE_KEYWORDS = [
    'for each', 'for every', 'apply', 'using',
    'where', 'when', 'given', 'then',
    'calculate', 'compute', 'find', 'determine'
]

def _is_pseudocode(self, line: str) -> bool:
    line_lower = line.lower().strip()
    
    # Check keywords
    if any(kw in line_lower for kw in PSEUDOCODE_KEYWORDS):
        return True
    
    # Check if it has NL patterns
    words = line_lower.split()
    if len(words) > 5 and not any(c in line for c in ['(', ')', '[', ']', '{']):
        return True
    
    return False

# In _parse_incomplete_code(), add:
if self._is_pseudocode(line):
    node_id = create_node_id(NodeType.PSEUDOCODE, f"pseudo_{line_num}", line_num)
    ir_node = IRNode(
        id=node_id,
        node_type=NodeType.PSEUDOCODE,
        name=f"pseudocode_{line_num}",
        status=NodeStatus.INCOMPLETE,
        spec_location=SourceLocation(line=line_num, col=0),
        spec_text=line,
        metadata={'is_pseudocode': True}
    )
    self.ir.add_node(ir_node)
    continue
```

### Win 3: Enhanced Generation Context (2 hours)

```python
# backend/diff_generator.py - enhance _build_generation_prompt()

def _build_generation_prompt(self, incomplete_nodes, context):
    lines = [
        "Generate Python code from this semiformal specification.",
        "",
        "IMPORTANT CONTEXT:",
        "- Analyze HOW functions are used to infer requirements",
        "- Consider data sources and outputs",
        "- Make implementations coherent with the full program",
        "",
        "FULL PROGRAM:",
        "```python",
        context['spec_source'],
        "```",
        ""
    ]
    
    # Add usage analysis
    if 'function_usage' in context:
        lines.append("USAGE PATTERNS:")
        for node in incomplete_nodes:
            if node.node_type == NodeType.FUNCTION_DEF:
                usage = context['function_usage'].get(node.name, {})
                if usage.get('call_contexts'):
                    lines.append(f"\n{node.name}() is called in:")
                    for ctx in usage['call_contexts']:
                        lines.append(f"  - {ctx}")
        lines.append("")
    
    # Add data flow
    if 'data_flow' in context:
        lines.append("DATA FLOW:")
        for var, flow in context['data_flow'].items():
            lines.append(f"  {var}: {flow}")
        lines.append("")
    
    lines.extend([
        "ELEMENTS TO IMPLEMENT:",
        ""
    ])
    
    for node in incomplete_nodes:
        if node.node_type == NodeType.FUNCTION_DEF:
            lines.append(f"- def {node.name}(...): {node.spec_text}")
        elif node.node_type == NodeType.NL_EXPRESSION:
            nl = node.metadata.get('rhs', '')
            lines.append(f"- {node.name} = {nl}")
    
    lines.extend([
        "",
        "Generate complete, executable Python code.",
        "Do NOT include markdown formatting.",
        ""
    ])
    
    return "\n".join(lines)
```

## Testing Strategy

### Test 1: Basic Stub Generation
```python
# Input (semiformal):
def process(data):
    ...

# Expected (Python):
def process(data):
    """TODO: Implement"""
    ...
```

### Test 2: Variable Placeholder
```python
# Input (semiformal):
x = split data into train and test

# Expected (Python):
x = ...  # split data into train and test
```

### Test 3: Pseudocode
```python
# Input (semiformal):
for each row where age > 18:
    apply filter

# Expected (Python):
# PSEUDOCODE: for each row where age > 18:
# PSEUDOCODE:     apply filter
```

### Test 4: Context-Aware Generation
```python
# Input (semiformal):
data = pd.read_csv('customers.csv')

def preprocess(df):
    ...

plot(preprocess(data))

# After generation, verify:
# - preprocess() knows it receives DataFrame
# - preprocess() knows output will be plotted
# - Includes appropriate data cleaning
```

## Next Steps Checklist

- [ ] Create `backend/skeleton_generator.py`
- [ ] Add `/generate-skeleton` endpoint
- [ ] Enhance `_parse_incomplete_code` with pseudocode detection
- [ ] Frontend: Call skeleton generation in `performAnalysis()`
- [ ] Test: Type on left, verify instant skeleton on right
- [ ] Add `NodeType.PSEUDOCODE` to `ir.py`
- [ ] Enhance generation prompt with usage context
- [ ] Create `backend/code_mapper.py` (for phase 2)
- [ ] Create `backend/code_abstractor.py` (for phase 4)
- [ ] Add tests for each scenario

## Key Files to Modify

1. `backend/ir.py` - Add `PSEUDOCODE` node type
2. `backend/ast_parser.py` - Enhance incomplete code parsing
3. `backend/skeleton_generator.py` - **NEW FILE**
4. `backend/main.py` - Add skeleton endpoint
5. `frontend/src/index.ts` - Call skeleton generation
6. `frontend/src/api.ts` - Add skeleton API call

## Success Criteria

**Phase 1 Complete When**:
- ✅ Type on left → Python skeleton updates in <500ms
- ✅ Function stubs appear immediately
- ✅ Variable placeholders show NL intent
- ✅ Pseudocode renders as comments
- ✅ Cmd+S still triggers full LLM generation
- ✅ Generated code respects program context

**User Experience**:
- Feels "live" and responsive
- Python side always shows valid Python (even if incomplete)
- Clear visual distinction between stub and generated code
- User understands when LLM is needed (save) vs instant (skeleton)

