# Refactored Architecture Diagram

## Edit Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (src/)                          │
│                                                                   │
│  ┌──────────────┐                                                │
│  │ User edits   │                                                │
│  │ semiformal   │                                                │
│  │ code         │                                                │
│  └──────┬───────┘                                                │
│         │                                                         │
│         │ Send raw edit (location, content, line)               │
│         │ NO edit type needed!                                   │
└─────────┼─────────────────────────────────────────────────────────┘
          │
          │ HTTP POST /edit/semiformal
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND (backend/)                          │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  1. main.py: edit_semiformal()                             │ │
│  │     - Receives raw edit from frontend                      │ │
│  │     - Passes to editor.on_semiformal_edit()                │ │
│  └─────────────────────────┬──────────────────────────────────┘ │
│                            │                                     │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  2. editor.py: BidirectionalEditor.on_semiformal_edit()    │ │
│  │     - Manages state (nodes, mappings, code)                │ │
│  │     - Calls translator.semiformal_to_python()              │ │
│  └─────────────────────────┬──────────────────────────────────┘ │
│                            │                                     │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  3. edit_router.py: EditTranslator                         │ │
│  │                                                              │ │
│  │  ┌───────────────────────────────────────────────────────┐ │ │
│  │  │ Step 1: EditTypeInferrer.infer_edit_type()            │ │ │
│  │  │                                                         │ │ │
│  │  │  Parse semiformal line:                                │ │ │
│  │  │  • Valid Python? → python_statement_edit               │ │ │
│  │  │  • Identifier changed? → identifier_rename             │ │ │
│  │  │  • Operator changed? → operator_change                 │ │ │
│  │  │  • Contains {}? → hole_edit                            │ │ │
│  │  │  • Natural language? → nl_edit                         │ │ │
│  │  └───────────────────────┬───────────────────────────────┘ │ │
│  │                          │                                  │ │
│  │                          ▼                                  │ │
│  │  ┌───────────────────────────────────────────────────────┐ │ │
│  │  │ Step 2: Route based on inferred type                  │ │ │
│  │  │                                                         │ │ │
│  │  │  Python edit types?                                    │ │ │
│  │  │    ├─ YES → _direct_translate()                        │ │ │
│  │  │    │         (preserve all other lines)                │ │ │
│  │  │    └─ Success? Return ✓                                │ │ │
│  │  │                                                         │ │ │
│  │  │  NL/hole edit OR direct failed?                        │ │ │
│  │  │    └─ _llm_translate()                                 │ │ │
│  │  │       (reparse, regenerate with diff)                  │ │ │
│  │  └───────────────────────┬───────────────────────────────┘ │ │
│  └────────────────────────────┼────────────────────────────────┘ │
│                               │                                  │
│              ┌────────────────┴────────────────┐                 │
│              │                                 │                 │
│              ▼                                 ▼                 │
│  ┌────────────────────────┐      ┌─────────────────────────┐   │
│  │ 4a. edit_operations.py │      │ 4b. generator.py        │   │
│  │                        │      │                         │   │
│  │ replace_statement():   │      │ generate_with_mapping():│   │
│  │  • Get line            │      │  • Re-parse semiformal  │   │
│  │  • Replace only that   │      │  • Call LLM (diff mode) │   │
│  │    line                │      │  • Return new code +    │   │
│  │  • Preserve all others │      │    mappings             │   │
│  │  • Keep indentation    │      │                         │   │
│  └────────────┬───────────┘      └──────────┬──────────────┘   │
│               │                             │                   │
│               └──────────┬──────────────────┘                   │
│                          │                                       │
│                          ▼                                       │
│               ┌─────────────────────┐                            │
│               │ EditResult          │                            │
│               │ • new_code          │                            │
│               │ • success           │                            │
│               │ • message           │                            │
│               │ • new_nodes?        │                            │
│               │ • new_mappings?     │                            │
│               └──────────┬──────────┘                            │
│                          │                                       │
└──────────────────────────┼───────────────────────────────────────┘
                           │
                           │ Return updated Python code
                           ▼
                    ┌──────────────┐
                    │   Frontend   │
                    │  updates UI  │
                    └──────────────┘
```

## Key Decision Points

### 1. Edit Type Inference

```
Input: "y = 20" (old: "y = 2")

EditTypeInferrer:
  ├─ Parse "y = 20" as Python → ✓ Valid
  ├─ Parse "y = 2" as Python → ✓ Valid
  ├─ Extract identifiers: {y} vs {y} → Same
  ├─ Extract operators: {=} vs {=} → Same
  └─ Extract literals: {20} vs {2} → DIFFERENT
      
Result: "literal_change"
```

### 2. Direct vs LLM Routing

```
Edit type: "python_statement_edit"

Router:
  ├─ Is in PYTHON_EDIT_TYPES? → YES
  │  └─ Call _direct_translate()
  │     └─ replace_statement(line=1, new="y = 20")
  │        └─ Success? → YES, return ✓
  │
  └─ [Not reached for Python edits]
```

```
Edit type: "nl_edit"

Router:
  ├─ Is in PYTHON_EDIT_TYPES? → NO
  │  
  └─ Call _llm_translate()
     ├─ Re-parse semiformal code
     ├─ Call generator.generate_with_mapping(existing_python=...)
     │  └─ LLM generates diff
     └─ Return new_code + new_nodes + new_mappings
```

## Direct Edit: No Code Loss

```
Before:
  Line 0: x = 1
  Line 1: y = 2     ← Edit this
  Line 2: z = 3
  Line 3: result = x + y + z

Direct edit (line 1, "y = 20"):
  lines = code.split('\n')        → [x=1, y=2, z=3, result=...]
  lines[1] = "y = 20"             → [x=1, y=20, z=3, result=...]
  return '\n'.join(lines)         → x=1\ny=20\nz=3\nresult=...

After:
  Line 0: x = 1
  Line 1: y = 20    ✓ Changed
  Line 2: z = 3     ✓ Preserved
  Line 3: result = x + y + z  ✓ Preserved
```

## Component Responsibilities

| Component | Responsibility | Key Method |
|-----------|---------------|------------|
| **Frontend** | Capture user edits, send to backend | `api.editSemiformal()` |
| **main.py** | HTTP endpoint, request validation | `edit_semiformal()` |
| **editor.py** | State management, orchestration | `on_semiformal_edit()` |
| **edit_router.py** | Edit type inference, routing | `semiformal_to_python()` |
| **edit_operations.py** | Direct AST/line edits | `replace_statement()` |
| **generator.py** | LLM code generation | `generate_with_mapping()` |
| **parser.py** | Parse semiformal → nodes | `parse()` |

## Data Flow

```
Semiformal Code (string)
  ↓ [parser.py]
IntentNodes (List[IntentNode])
  ↓ [generator.py]
Python Code (string) + Mappings (List[Mapping])
  ↓ [edit_router.py] ← User Edit
Python Code' (string) + Mappings' (List[Mapping])
  ↓
Frontend displays updated code
```

