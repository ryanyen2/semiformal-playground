# Semiformal Programming System Architecture

## Overview

The semiformal programming system enables bidirectional synchronization between **semiformal code** (mix of Python, natural language, and holes) and **generated Python code**. The system uses a sophisticated DAG-based dependency tracking system to propagate changes intelligently.

## Core Concepts

### 1. Semiformal Code

Semiformal code is a hybrid syntax that combines:
- **Pure Python**: Standard Python statements
- **Natural Language (NL)**: English descriptions of operations (e.g., `data = load the dataset`)
- **Holes**: Placeholders for future implementation (`x = {}` or `x = {hint}`)
- **Anchor Comments**: Semantic markers (`#>`) that enable bidirectional mapping

Example:
```python
def preprocessing(data):  #> preprocessing
    #> data; coerce; to; dataframe
    data = coerce to dataframe
    
    #> numeric_cols; select numeric
    numeric_cols = select numeric
    
    return data

data = load_dataset('iris.csv')  #> data; load_dataset
df = preprocessing(data)  #> df; preprocessing; data
```

### 2. Bidirectional Mapping

The system maintains **precise mappings** between semiformal nodes and generated Python code:
- **Semiformal → Python**: Each intent node maps to generated code location(s)
- **Python → Semiformal**: Generated code includes anchor comments linking back to semiformal nodes
- **Anchors**: `#>` marks in Python code create traceable connections

This enables:
- **Forward sync**: Changes in semiformal → regenerate Python
- **Backward sync**: Inferred code from Python → suggest semiformal additions
- **Precise editing**: Changes target specific nodes without full regeneration

## System Architecture

### Layer 1: Parsing (`parser.py`)

**Purpose**: Parse semiformal code into structured intent nodes

**Key Components**:
- `IntentNode`: Semantic unit representing variables, functions, NL phrases, holes
- `SemiformalParser`: Converts semiformal text → list of IntentNodes

**Node Types**:
- `identifier`: Variable names (with role: target/reference)
- `function_call`: Function invocations
- `function_def`: Function definitions
- `nl_phrase`: Natural language fragments
- `hole`: Placeholders for future code
- `operator`, `literal`, `keyword`: Basic Python elements
- `expr_stmt`: Complete expression statements
- `python_stmt`: Generic Python statements

**Parsing Strategy**:
1. Try parsing entire code as valid Python (using AST)
2. If fails, fall back to line-by-line hybrid parsing
3. Handle multiline statements
4. Extract dependencies between nodes

### Layer 2: Data Flow Graph (`dataflow_graph.py`)

**Purpose**: Track dependencies between computational units using a Directed Acyclic Graph (DAG)

**Key Components**:
- `DataFlowNode`: Represents computational unit with dependencies
- `DataFlowGraph`: DAG of nodes with dependency edges
- `GraphBuilder`: Constructs graph from IntentNodes
- `ChangeDetector`: Compares two graphs to identify structural changes
- `UpdatePropagator`: Determines what needs regeneration via graph traversal

**Node Kinds**:
- `VARIABLE`: Variable assignments
- `FUNCTION_CALL`: Function invocations
- `LITERAL`: Constant values
- `PARAMETER`: Function parameters
- `EXPRESSION`: Generic expressions
- `IMPORT`: Import statements

**Change Types**:
- `NODE_ADDED`: New node in graph
- `NODE_REMOVED`: Node deleted
- `NODE_MODIFIED`: Node content changed
- `EDGE_ADDED`: New dependency
- `EDGE_REMOVED`: Dependency removed
- `SUBGRAPH_REWIRED`: Complex structural change

**Update Propagation Algorithm**:
1. Identify directly affected nodes (what changed)
2. Propagate impact through DAG (find all dependents recursively)
3. Build `UpdateSpec` with:
   - Nodes to regenerate
   - Topological order for regeneration
   - Context for each node (dependencies, metadata)

### Layer 3: Code Generation (`generator.py`)

**Purpose**: Generate Python code from intent nodes with dependency-aware context

**Key Components**:
- `CodeGenerator`: Orchestrates generation with LLM
- `create_annotated_semiformal_text()`: Converts nodes → annotated semiformal format
- `strip_function_bodies_for_regeneration()`: Removes stub implementations

**Generation Flow**:
1. Build data flow graph from intent nodes
2. Detect changes compared to previous version
3. Compute update specification (what needs regeneration)
4. **Identify functions to strip** (NEW: prevents bias from old stubs)
5. **Strip function bodies** for functions requiring regeneration (NEW)
6. Annotate semiformal with semantic anchors
7. Build generation context from DAG analysis
8. Call LLM with prompt + context
9. Postprocess output (anchor mapping, diff application)

**Anchor Format**:
- Semiformal spec: Anchors ABOVE lines (`#> anchor1; anchor2`)
- Generated Python: Anchors INLINE at end of lines (`code  #> anchor1; anchor2`)

### Layer 4: LLM Service (`llm_service.py`)

**Purpose**: Interface with OpenAI API for code generation

**Key Components**:
- `LLMService`: Manages API calls with retry logic
- `SYSTEM_PROMPT`: Comprehensive instructions for code generation
- `ANCHOR_RULES`: Detailed anchor placement guidelines

**Prompt Structure**:
1. **System Prompt**: Static instructions + reasoning guidelines
2. **Few-shot Examples**: Demonstration of anchor usage and patterns
3. **Dynamic Context**: DAG-derived dependency analysis
4. **Semiformal Spec**: Annotated current code with anchors
5. **Anchor Rules**: Reference for precise placement
6. **Focus Areas**: Nodes requiring special attention

**Key Instructions to LLM**:
- Generate COMPLETE code (not diffs - backend handles that)
- Place `#>` anchors inline at end of lines
- Use `#<` ONLY for inferred code when no `#>` exists
- Update ALL callers when signatures change
- Adapt to data flow changes (e.g., dataset switch)
- Generate FRESH implementations for stripped functions

### Layer 5: Postprocessing (`postprocessing.py`)

**Purpose**: Parse LLM output, create mappings, detect unmapped code

**Key Components**:
- `CodePostprocessor`: Analyzes generated code
- Anchor parsing: Extract `#>` and `#<` markers
- AST analysis: Parse generated Python
- Mapping creation: Link intent nodes → generated code
- Unmapped detection: Find inferred code without anchors
- Diff application: Apply changes to existing code

### Layer 6: Editing (`editor.py`, `edit_router.py`, `edit_operations.py`)

**Purpose**: Handle user edits and route to appropriate update strategy

**Key Components**:
- `BidirectionalEditor`: Main orchestrator
- `EditTranslator`: Converts user edits → internal operations
- `UpdateDecider`: Determines if regeneration needed
- `EditOperations`: Direct AST manipulation for simple edits

**Edit Flow**:
1. User edits semiformal code
2. Parse new semiformal → intent nodes
3. Detect changes via DAG comparison
4. **Decision Point**:
   - Simple edit → Direct AST manipulation (fast)
   - Complex edit → Full regeneration via LLM
5. Update mappings
6. Return updated Python code

### Layer 7: Tree Mapping (`tree_mapper.py`)

**Purpose**: Map IR (Intent Representation) tree to AST tree using structural similarity

**Key Components**:
- `TreeNode`: Unified tree node representation
- `TreeMapper`: Two-phase matching algorithm
  1. Coarse-grained: Match major subtrees (functions, statements)
  2. Fine-grained: Match tokens within subtrees

**Mapping Types**:
- `EXACT`: Perfect structural + content match
- `STRUCTURAL`: Structure matches, content differs
- `SEMANTIC`: Semantic equivalence (NL → code)
- `PARTIAL`: Partial overlap
- `UNMAPPED`: No mapping found

## How Different Edit Types Trigger Different Actions

### 1. Simple Variable Assignment
**Edit**: `x = 5` → `x = 10`

**Action**: Direct AST manipulation (no LLM)
- Update literal value in Python AST
- Fast, deterministic

### 2. Add NL Phrase to Assignment
**Edit**: `x = 10` → `x = load the data`

**Action**: LLM generation
- DAG detects node modified (literal → NL phrase)
- Mark `x` and dependents for regeneration
- Generate fresh code for affected nodes

### 3. Change Data Source
**Edit**: `data = load_dataset('iris.csv')` → `data = load_dataset('titanic.csv')`

**Action**: LLM generation with cascade
- DAG detects `data` node modified
- Propagate to ALL dependents (e.g., `preprocessing(data)`)
- **Strip bodies** of dependent functions (NEW)
- LLM generates fresh implementations adapted to new dataset

### 4. Add Function Parameter
**Edit**: `def preprocess(data)` → `def preprocess(data, threshold)`

**Action**: LLM generation with signature update
- DAG detects function signature change
- Find ALL call sites
- Mark function definition + all callers for regeneration
- LLM updates signature, calls, and implementation

### 5. Add Hole
**Edit**: Add line `result = {process the data}`

**Action**: LLM generation
- Parse new hole node
- DAG detects node added
- Generate implementation for hole
- Create mapping

### 6. Complex Restructuring
**Edit**: Reorder statements, change dependencies

**Action**: Full regeneration
- DAG detects multiple nodes affected
- Compute transitive closure of dependents
- Generate all affected code in topological order

## Key Insights

### Why DAG-Based Dependency Tracking?

Replaces heuristics with **principled graph theory**:
- **Precise**: Knows exactly what depends on what
- **Efficient**: Only regenerates what's needed
- **Correct**: Topological order ensures dependencies met
- **Generic**: No hardcoded schemas or assumptions

### Why Strip Function Bodies?

Prevents LLM bias:
- Old stub implementations are **throwaway** code
- New context (data source, dependencies) requires **fresh** thinking
- Stripping forces LLM to reason from scratch
- Produces better, more adapted implementations

### Why Anchor Comments?

Enable precise bidirectional mapping:
- **Traceability**: Every generated line traces back to semiformal
- **Granular edits**: Target specific nodes without full regeneration
- **Debugging**: Understand what each line implements
- **Round-trip**: Python → semiformal suggestions

## Data Flow Example

**Initial Semiformal**:
```python
data = load_dataset('iris.csv')
df = preprocessing(data)
```

**Step 1: Parse** → IntentNodes:
- Node 1: `data` (identifier, target)
- Node 2: `load_dataset` (function_call, args: ['iris.csv'])
- Node 3: `df` (identifier, target)
- Node 4: `preprocessing` (function_call, args: [data])

**Step 2: Build DAG**:
```
[iris.csv] → [load_dataset] → [data] → [preprocessing] → [df]
```

**Step 3: User edits** `'iris.csv'` → `'titanic.csv'`

**Step 4: Detect Changes**:
- `iris.csv` node removed
- `titanic.csv` node added
- `load_dataset` node modified (different arg)

**Step 5: Propagate Impact**:
- Direct: `load_dataset`, `data`
- Indirect: `preprocessing` (depends on `data`)
- Transitive: `df` (depends on `preprocessing`)

**Step 6: Identify Functions to Strip**:
- `preprocessing` is user-defined and in regeneration set
- Add to strip set

**Step 7: Strip Function Bodies**:
```python
def preprocessing(data):  #> preprocessing
    pass  # body omitted - will be regenerated

data = load_dataset('titanic.csv')
df = preprocessing(data)
```

**Step 8: Generate Context**:
- Dataset changed: iris → titanic
- Preprocessing needs adaptation
- Consider Titanic columns: Age, Sex, Pclass, Fare, Embarked

**Step 9: LLM Generates**:
```python
def preprocessing(data):  #> preprocessing
    data = pd.DataFrame(data)  #> data; coerce; to; dataframe
    
    # Titanic-specific preprocessing
    data['Age'] = pd.to_numeric(data['Age'], errors='coerce')  #< coerce age
    data['Fare'] = pd.to_numeric(data['Fare'], errors='coerce')  #< coerce fare
    data = pd.get_dummies(data, columns=['Sex', 'Embarked'])  #< encode categoricals
    
    return data

data = load_dataset('titanic.csv')  #> data; load_dataset
df = preprocessing(data)  #> df; preprocessing; data
```

## Summary

The semiformal programming system is a sophisticated architecture combining:
- **Parsing**: Flexible hybrid syntax handling
- **DAG**: Principled dependency tracking
- **Generation**: Context-aware LLM code generation
- **Mapping**: Precise bidirectional traceability
- **Editing**: Intelligent routing between direct edits and regeneration

The key innovation is using **graph-based change propagation** rather than heuristics, enabling correct, efficient, and generalizable code evolution as semiformal specifications change.
