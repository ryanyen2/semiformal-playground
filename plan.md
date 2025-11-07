Excellent! This is a much more concrete and feasible approach. The heading-based structural mapping is elegant and solves the fuzzy mapping problem. Let me design the full system:

## Core Design: Heading-Hierarchy Mapping

```markdown
# Authentication Module
<!-- @repo-folder: src/auth -->
<!-- @ai-generated: 2025-01-15 -->

User authentication and session management for the application.

## password_hashing.py
<!-- @repo-file: src/auth/password_hashing.py -->
<!-- @dependencies: bcrypt, typing -->

Utilities for secure password hashing and verification.

### hash_password(password: str) -> str
<!-- @repo-function: hash_password -->
<!-- @ai-detail: Uses bcrypt with 12 rounds, adds random salt -->

Hashes a plaintext password using bcrypt algorithm with 12 salt rounds.
Returns the hashed string that can be stored in database.

### verify_password(password: str, hashed: str) -> bool
<!-- @repo-function: verify_password -->

Verifies a plaintext password against a stored bcrypt hash.
```

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│  Enhanced Markdown Document (Source of Truth)       │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│  # Module        ← Folder mapping                   │
│  ## File         ← File mapping                     │
│  ### Function    ← Function/class mapping           │
│  <!-- @meta --> ← Machine-readable annotations      │
└──────────────┬──────────────────────────────────────┘
               │
               ↓ Parse (Custom Markdown Parser)
┌──────────────────────────────────────────────────────┐
│  Document AST + Feature Graph (IR)                   │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│  Node {                                              │
│    level: 1|2|3                                      │
│    title: "hash_password"                            │
│    prose: "Hashes plaintext..."                      │
│    annotations: {@repo-function, @dependencies}      │
│    children: []                                      │
│    code_ref: CodeArtifact | null                     │
│  }                                                   │
└──────────────┬───────────────────────────────────────┘
               │
               ↓ Generate (Claude Code API)
┌──────────────────────────────────────────────────────┐
│  Generated Codebase                                  │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│  src/auth/password_hashing.py:                       │
│    # @doc: ##password_hashing.py                     │
│    def hash_password(password: str) -> str:          │
│        # @doc: ###hash_password                      │
│        """Hashes plaintext..."""                     │
│        import bcrypt                                 │
│        return bcrypt.hashpw(...)                     │
└──────────────┬───────────────────────────────────────┘
               │
               ↓ Analyze (AST + Imports + Call Graph)
┌──────────────────────────────────────────────────────┐
│  Extracted Feature Tree                              │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│  - Actual dependencies (bcrypt)                      │
│  - Actual function signatures                        │
│  - Call relationships                                │
│  - Underspecified details (salt rounds=12)           │
└──────────────┬───────────────────────────────────────┘
               │
               ↓ Sync back
┌──────────────────────────────────────────────────────┐
│  Document + AI Annotations                           │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│  ### hash_password(password: str) -> str             │
│  <!-- @ai-detail: Uses bcrypt with 12 rounds -->     │
│  <!-- @ai-dependencies: bcrypt==4.1.2 -->            │
│                                                      │
│  User prose stays unchanged, AI adds details         │
└──────────────────────────────────────────────────────┘
```

## Custom Markup Language Syntax

### 1. Structural Headings (Required)

```markdown
# Module Name          → Folder (src/module_name/)
## file_name.py        → File
### function_name()    → Function/Class
#### method_name()     → Class method (optional depth)
```

### 2. Inline Annotations (HTML comments)

```markdown
<!-- @repo-folder: src/auth -->
<!-- @repo-file: src/auth/password.py -->
<!-- @repo-function: hash_password -->
<!-- @repo-class: UserAuthenticator -->

<!-- @ai-generated: 2025-01-15T10:30:00Z -->
<!-- @ai-detail: Implementation uses bcrypt with 12 rounds -->
<!-- @ai-dependencies: bcrypt==4.1.2, typing-extensions -->
<!-- @ai-signature: (password: str, salt_rounds: int = 12) -> str -->

<!-- @human-edited: 2025-01-16T14:20:00Z -->
<!-- @conflict: type-mismatch -->
<!-- @warning: Missing error handling for invalid input -->
```

### 3. Special Blocks

````markdown
::: ai-implementation
**Auto-generated details** (do not edit manually)

```python-signature
def hash_password(password: str, salt_rounds: int = 12) -> str
```

Dependencies: `bcrypt==4.1.2`  
Complexity: O(1)  
Last sync: 2025-01-15
:::

::: conflict
**⚠️ Sync conflict detected**

Document says: "hash with SHA-256"  
Code implements: bcrypt hashing

[Accept Document] [Accept Code] [Resolve Manually]
:::

::: human-zone
This section is manually maintained and won't be auto-regenerated.
You can document complex business logic here.
:::
````

## Concrete Workflow

### Phase 1: Initial Generation

```markdown
# Authentication
<!-- @repo-folder: src/auth -->

## password.py
<!-- @repo-file: src/auth/password.py -->

### hash_password
Securely hash user passwords.
```

**System actions:**
1. Parse document → Build AST
2. Call Claude Code API with context:
   ```
   Create src/auth/password.py with hash_password function.
   Spec: "Securely hash user passwords"
   ```
3. Receive generated code
4. Analyze code (AST parser finds: bcrypt import, 12 rounds, type hints)
5. **Sync back to document:**

```markdown
### hash_password
<!-- @ai-generated: 2025-01-15 -->
<!-- @ai-dependencies: bcrypt==4.1.2 -->
<!-- @ai-signature: (password: str) -> str -->
<!-- @ai-detail: Uses bcrypt with 12 salt rounds -->

Securely hash user passwords.

::: ai-implementation
```python
def hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
```
:::
```

### Phase 2: User Edits Document

User changes requirement:

```diff
  ### hash_password
- Securely hash user passwords.
+ Hash passwords with argon2id algorithm for better security.
```

**System actions:**
1. Detect change in `###hash_password` section
2. Find code artifact via `@repo-function` annotation
3. Mark as "needs regeneration":
   ```markdown
   <!-- @needs-regen: argon2id algorithm change -->
   ```
4. Show in editor with visual indicator (custom linting)

### Phase 3: Regeneration

User triggers regeneration:

1. System extracts new requirement: "argon2id algorithm"
2. Loads existing code as context
3. Calls Claude Code API:
   ```
   Modify src/auth/password.py::hash_password
   Old spec: "Securely hash"
   New spec: "Hash with argon2id algorithm"
   
   Existing code:
   [current implementation]
   
   Dependencies to consider: bcrypt → argon2-cffi
   ```
4. Receives updated code
5. **Conflict detection:**
   - Compare old vs new code
   - If only implementation changes → auto-apply
   - If signature changes → flag conflict

```markdown
::: conflict
**⚠️ Function signature changed**

Old: `hash_password(password: str) -> str`  
New: `hash_password(password: str, time_cost: int = 2) -> str`

This may break callers:
- `src/auth/login.py::authenticate()` ← 2 callers
- `src/api/signup.py::create_user()` ← 1 caller

[Accept & Update Callers] [Reject] [Review]
:::
```

### Phase 4: User Edits Code Directly

Developer manually modifies code:

```python
# src/auth/password.py
def hash_password(password: str) -> str:
    # Added custom validation
    if len(password) < 8:
        raise ValueError("Password too short")
    
    import bcrypt
    return bcrypt.hashpw(...)
```

**System actions (on git commit hook or manual sync):**

1. Detect code changed but document didn't
2. Extract new details:
   - Found validation logic: `len(password) < 8`
   - Found exception: `ValueError`
3. **Sync to document:**

```markdown
### hash_password
<!-- @ai-detail: Validates password length (min 8 chars) -->
<!-- @ai-detail: Raises ValueError if validation fails -->
<!-- @human-edited: 2025-01-16 by @developer -->

Hash passwords with argon2id algorithm for better security.

::: human-zone
**Implementation notes:**
- Minimum length: 8 characters
- Raises `ValueError` for invalid input
- Added by @developer on 2025-01-16
:::
```

## Custom Linting Rules

```yaml
# .doclint.yml
rules:
  - id: missing-file-mapping
    level: error
    pattern: "## *.py without @repo-file annotation"
    
  - id: stale-ai-detail
    level: warning
    check: "@ai-detail timestamp > 30 days old"
    
  - id: needs-regen
    level: info
    pattern: "<!-- @needs-regen -->"
    message: "Section modified, regeneration needed"
    
  - id: unresolved-conflict
    level: error
    pattern: "::: conflict"
    
  - id: orphaned-code
    level: warning
    check: "code exists but no doc section"
```

**Editor integration (VS Code extension):**

```typescript
// Document has inline decorations:

### hash_password              // 🟢 synced
<!-- @needs-regen -->          // 🟡 needs attention

::: conflict                   // 🔴 must resolve
```

## Dependency Graph Extraction

After code generation, build dependency graph:

```python
# dependency_analyzer.py
import ast
import networkx as nx

def extract_dependencies(codebase_path, doc_ast):
    """
    Parse all Python files and build:
    1. Import graph
    2. Call graph  
    3. Data flow graph
    
    Link back to document sections via @doc comments in code
    """
    
    graph = nx.DiGraph()
    
    for file_path in find_python_files(codebase_path):
        tree = ast.parse(read_file(file_path))
        
        # Find @doc comments → link to document sections
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                doc_ref = extract_doc_comment(node)  # "###hash_password"
                
                # Extract calls made by this function
                calls = extract_function_calls(node)
                
                graph.add_node(doc_ref, 
                    code_path=f"{file_path}::{node.name}",
                    type="function")
                
                for call in calls:
                    graph.add_edge(doc_ref, resolve_call(call))
    
    return graph
```

**Store in IR:**

```json
{
  "document": "README.md",
  "last_sync": "2025-01-15T10:30:00Z",
  "mappings": {
    "###hash_password": {
      "code_path": "src/auth/password.py::hash_password",
      "dependencies": {
        "imports": ["bcrypt"],
        "calls": [],
        "called_by": [
          "###authenticate",
          "###create_user"
        ]
      },
      "signature": "(password: str) -> str",
      "last_human_edit": null,
      "last_ai_edit": "2025-01-15T10:30:00Z"
    }
  },
  "dependency_graph": {
    "nodes": [...],
    "edges": [...]
  }
}
```

## Change Impact Analysis

When user edits document section:

```python
def analyze_impact(changed_section_id, ir):
    """
    Given: user edited "###hash_password"
    Return: what code will be affected
    """
    
    affected = {
        "direct": ir.mappings[changed_section_id].code_path,
        "callers": [],
        "dependencies": []
    }
    
    # Find all sections that depend on this one
    graph = ir.dependency_graph
    
    for caller in graph.predecessors(changed_section_id):
        affected["callers"].append({
            "doc_section": caller,
            "code_path": ir.mappings[caller].code_path,
            "reason": "calls modified function"
        })
    
    # Find shared dependencies that might need updates
    deps = ir.mappings[changed_section_id].dependencies.imports
    for other_section, mapping in ir.mappings.items():
        if other_section != changed_section_id:
            shared = set(deps) & set(mapping.dependencies.imports)
            if shared:
                affected["dependencies"].append({
                    "doc_section": other_section,
                    "shared_deps": list(shared)
                })
    
    return affected
```

**Show in UI:**

```markdown
### hash_password
<!-- @needs-regen: algorithm changed to argon2id -->
<!-- @impact: 2 callers, 0 shared dependencies -->

📊 **Impact Analysis**
- Direct: `src/auth/password.py::hash_password`
- Callers that may need updates:
  - [###authenticate](#authenticate) in login flow
  - [###create_user](#create_user) in signup flow
- Shared dependencies: none

[Regenerate Function Only] [Regenerate + Update Callers]
```

## Handling Underspecified Parts

During initial generation, LLM may fill in missing details:

**User writes (minimal):**
```markdown
### hash_password
Hash the password securely.
```

**After generation and analysis, system adds:**
```markdown
### hash_password
<!-- @ai-signature: (password: str) -> str -->
<!-- @ai-dependencies: bcrypt==4.1.2 -->
<!-- @ai-detail: Uses bcrypt with 12 salt rounds -->
<!-- @ai-note: Added error handling for empty strings -->

Hash the password securely.

::: ai-implementation-notes
The generated implementation:
- Uses bcrypt hashing (industry standard)
- Applies 12 salt rounds (OWASP recommended)
- Raises `ValueError` for empty password
- Returns base64-encoded hash string

If you want different behavior, edit the prose above and regenerate.
:::
```

**User can then:**
1. Accept these details (do nothing)
2. Override them (edit prose + regenerate)
3. Manually edit code (system will detect and update notes)

## Conflict Resolution UI

When document and code diverge:

```markdown
### authenticate
<!-- @conflict: signature-mismatch -->

::: conflict
**⚠️ Document and code are out of sync**

**Document says:**
> Authenticate user with email and password

**Code implements:**
```python
def authenticate(email: str, password: str, mfa_code: str = None) -> bool:
    # Added MFA support in commit abc123
```

**Detected changes:**
- ➕ New parameter: `mfa_code` (optional)
- 📝 Implementation added MFA validation

**Resolution options:**

1. **Update document to match code** (recommended)
   - Adds "with optional MFA" to prose
   - Updates signature annotation
   
2. **Regenerate code from document**
   - Removes MFA parameter
   - ⚠️ May break 3 test cases
   
3. **Manual resolution**
   - Edit document to explicitly describe MFA
   - Keep code as-is
   - Mark conflict as resolved

[Option 1] [Option 2] [Option 3]
:::
```

## Implementation Priorities

### MVP (Week 1-2): Core Parsing + Generation
```typescript
class DocumentParser {
  parse(markdown: string): DocumentAST
  extractMappings(): HeadingToCodeMap
  validateStructure(): LintErrors[]
}

class CodeGenerator {
  generate(ast: DocumentAST): Promise<GeneratedCode>
  // Calls Claude Code API
}

class Synchronizer {
  analyzeCode(code: GeneratedCode): FeatureTree
  updateDocument(doc: DocumentAST, features: FeatureTree): DocumentAST
}
```

### Phase 2 (Week 3-4): Incremental Updates
```typescript
class ChangeDetector {
  detectDocumentChanges(oldAST, newAST): Change[]
  findAffectedCode(change: Change, ir: IR): CodeArtifact[]
}

class ConflictResolver {
  detectConflicts(doc: DocumentAST, code: Codebase): Conflict[]
  suggestResolution(conflict: Conflict): Resolution[]
}
```

### Phase 3 (Week 5-6): Tooling
```typescript
class CustomLinter {
  rules: LintRule[]
  lint(document: string): Diagnostic[]
}

class VSCodeExtension {
  provideDecorations(): Decoration[]
  provideCodeActions(): CodeAction[]  // Quick fixes for conflicts
  provideHover(): HoverInfo  // Show impact analysis
}
```

## Key Advantages of This Approach

✅ **Explicit structure via headings** - No embedding needed, clear mapping  
✅ **Bidirectional sync** - Code changes flow back to document  
✅ **Conflict surfacing** - Custom blocks make issues visible  
✅ **Incremental updates** - Only regenerate changed sections  
✅ **Impact analysis** - Dependency graph shows ripple effects  
✅ **Human-in-loop** - Conflicts require explicit resolution  
✅ **Standard Markdown base** - Readable without special tools  
✅ **Extensible** - Can add more annotation types as needed  

## Potential Issues & Mitigations

### Issue 1: Heading Structure Discipline Required

**Problem:** Users might not follow `#`/`##`/`###` convention  
**Mitigation:** 
- Linter enforces structure
- Template generator for new sections
- CLI: `doccoder add-function "hash_password" --in auth.password`

### Issue 2: Merge Conflicts in Git

**Problem:** HTML comments create noise in diffs  
**Mitigation:**
- Store IR separately (`.doccoder/mappings.json`)
- Only keep essential annotations in doc
- Custom git merge driver

### Issue 3: Over-annotation Clutter

**Problem:** Too many `<!-- -->` comments make doc unreadable  
**Mitigation:**
- Collapse annotations in editor (VS Code folding)
- Hide by default, show on hover
- Move verbose details to `::: blocks` that can be folded

### Issue 4: Stale Annotations

**Problem:** `@ai-detail` becomes outdated  
**Mitigation:**
- Timestamp every annotation
- Linter warns about old annotations (>30 days)
- Regular sync command: `doccoder sync --update-all`

## Next Steps to Validate

1. **Create minimal example:**
   - 1 module, 2 files, 5 functions
   - Write document with headings
   - Manually create expected IR
   - Mock Claude Code API response
   - Verify mapping works

2. **Test edit cycle:**
   - Change one function's prose
   - Simulate regeneration
   - Check impact analysis
   - Verify callers detected

3. **Test conflict:**
   - Manually edit generated code
   - Run sync
   - Check conflict block generated correctly

4. **Build parser prototype:**
   - Extend Textlint for custom annotations
   - Parse heading hierarchy
   - Extract `<!-- @repo-* -->` comments
   - Build AST + IR

Would you like me to create a concrete example showing the full cycle for a specific feature (e.g., the password hashing example), with:
1. Initial document
2. Generated code with `@doc` comments
3. Extracted feature tree
4. Synced document with AI annotations
5. A simulated edit + conflict resolution?