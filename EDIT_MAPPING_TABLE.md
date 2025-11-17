# Comprehensive Edit Mapping Table: Semiformal ↔ Python

This document maps all possible edits in the semiformal specification to their corresponding Python code transformations.

## Legend

- **Direct**: Can be translated directly without LLM (AST manipulation)
- **LLM**: Requires LLM to generate/regenerate code
- **Template**: Uses predefined code templates
- **Regenerate**: Needs to regenerate entire function/block
- **Placeholder**: Uses temporary placeholder in code
- **Hole**: Uses `{}` or `{hint}` syntax for LLM fill
- **Python Edit**: Edit happens on Python side
- **Propagation**: Required/Optional/Forbidden back to spec

---

## Part 1: Semiformal → Python Edits

### A. Identifier Edits (LHS)

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Variable rename (simple) | `x = ...` → `y = ...` | ✅ Yes | ❌ No | ❌ No | Rename variable throughout scope | **Direct** (AST) | Update all references |
| Variable rename (NL) | `data = load file` → `dataset = load file` | ✅ Yes | ❌ No | ❌ No | Rename variable + trigger regen | **Direct + Regenerate** | Regen RHS since NL changed context |
| Add variable to LHS | `x = ...` → `x, y = ...` | ⚠️ Partial | ✅ Yes | ❌ No | Convert to tuple unpacking, add placeholder for y | **Direct + Placeholder** | RHS needs LLM to determine y value |
| Remove variable from LHS | `x, y = ...` → `x = ...` | ✅ Yes | ❌ No | ❌ No | Remove from tuple, adjust RHS | **Direct** | May need to index RHS `[0]` |
| Add multiple variables | `x = ...` → `x, y, z = ...` | ⚠️ Partial | ✅ Yes | ❌ No | Create tuple unpacking, LLM determines values | **Template + LLM** | Need to infer what y, z should be |

### B. Identifier Edits (Function Names)

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Function rename | `def process():` → `def transform():` | ✅ Yes | ❌ No | ❌ No | Rename function + all call sites | **Direct** (AST) | No LLM needed |
| Function call rename | `result = old_func()` → `result = new_func()` | ✅ Yes | ❌ No | ❌ No | Update call site | **Direct** | Check if function exists |
| Add function call | `result = x` → `result = process(x)` | ⚠️ Partial | ✅ Yes | ❌ No | Insert call, create stub if undefined | **Direct + Template** | May need stub generation |

### C. Identifier Edits (Parameters)

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Add parameter | `def f(a):` → `def f(a, b):` | ✅ Yes | ❌ No | ❌ No | Add to signature + regenerate body | **Direct + Regenerate** | Body must use new param |
| Remove parameter | `def f(a, b):` → `def f(a):` | ✅ Yes | ❌ No | ❌ No | Remove from signature + regenerate body | **Direct + Regenerate** | Remove param usage in body |
| Rename parameter | `def f(old):` → `def f(new):` | ✅ Yes | ❌ No | ❌ No | Rename in signature + body | **Direct** (AST) | Rename all references in scope |
| Reorder parameters | `def f(a, b):` → `def f(b, a):` | ✅ Yes | ❌ No | ❌ No | Reorder in signature + update calls | **Direct** | Update all call sites |
| Add default value | `def f(a):` → `def f(a=5):` | ✅ Yes | ❌ No | ❌ No | Add default to signature | **Direct** | May affect body logic |

### D. Operator Edits

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Arithmetic operator | `x + y` → `x - y` | ✅ Yes | ❌ No | ❌ No | Replace operator token | **Direct** (AST) | Simple token swap |
| Comparison operator | `x > y` → `x >= y` | ✅ Yes | ❌ No | ❌ No | Replace operator token | **Direct** (AST) | Simple token swap |
| Boolean operator | `x and y` → `x or y` | ✅ Yes | ❌ No | ❌ No | Replace operator token | **Direct** (AST) | Simple token swap |
| Assignment operator | `x = y` → `x += y` | ✅ Yes | ❌ No | ❌ No | Change assignment type | **Direct** (AST) | AugAssign vs Assign |

### E. Literal Edits

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Number change | `x = 5` → `x = 10` | ✅ Yes | ❌ No | ❌ No | Replace literal value | **Direct** | Exact replacement |
| String change | `s = "hello"` → `s = "world"` | ✅ Yes | ❌ No | ❌ No | Replace string literal | **Direct** | Exact replacement |
| Boolean change | `flag = True` → `flag = False` | ✅ Yes | ❌ No | ❌ No | Replace boolean value | **Direct** | Exact replacement |
| None/empty change | `x = None` → `x = []` | ✅ Yes | ❌ No | ❌ No | Replace literal | **Direct** | Type may affect downstream |

### F. Expression Edits

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Add function argument | `f(a)` → `f(a, b)` | ⚠️ Partial | ✅ Yes | ❌ No | Add arg, may need placeholder value | **Direct + Placeholder** | Need to determine `b` value |
| Remove function argument | `f(a, b)` → `f(a)` | ✅ Yes | ❌ No | ❌ No | Remove argument | **Direct** | Check function signature |
| Reorder arguments | `f(a, b)` → `f(b, a)` | ✅ Yes | ❌ No | ❌ No | Reorder arguments | **Direct** | Must match function signature |
| Add keyword argument | `f(a)` → `f(a, key=val)` | ⚠️ Partial | ✅ Yes | ❌ No | Add kwarg, may need value inference | **Direct + LLM** | Need to determine appropriate value |
| Change to NL expression | `x = [1,2,3]` → `x = list of numbers` | ❌ No | ❌ No | ✅ Yes (implicit) | Mark for LLM generation | **LLM** | Convert to NL node, regenerate |

### G. Natural Language (NL) Edits

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Fill empty hole | `x = {}` → `x = {use pandas}` | ❌ No | ❌ No | ✅ Yes | LLM generates from hint | **LLM** | Hole filled with hint |
| Add hint to hole | `x = {}` → `x = {sklearn preprocessing}` | ❌ No | ❌ No | ✅ Yes | LLM uses hint for generation | **LLM** | More constrained generation |
| Modify NL phrase | `x = load data` → `x = load and clean data` | ❌ No | ❌ No | ❌ No (implicit) | Regenerate with new intent | **LLM** | Semantic change |
| Add NL constraint | `x = load data` → `x = load data from CSV` | ❌ No | ❌ No | ❌ No (implicit) | Regenerate with constraint | **LLM** | More specific generation |
| Convert NL to Python | `x = load data` → `x = pd.read_csv("data.csv")` | ✅ Yes | ❌ No | ❌ No | Replace with concrete Python | **Direct** | User provided exact code |
| Convert Python to NL | `x = pd.read_csv("data.csv")` → `x = load data from CSV` | ❌ No | ❌ No | ✅ Yes | Create NL node + mark as hole | **Template + Hole** | Abstraction direction |

### H. Statement-Level Edits

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Insert Python statement | Add `print(x)` | ✅ Yes | ❌ No | ❌ No | Insert at dependency-aware position | **Direct** | Check dependencies |
| Insert NL statement | Add `validate the data` | ❌ No | ❌ No | ✅ Yes (implicit) | LLM generates implementation | **LLM** | Generate Python from NL |
| Delete statement | Remove line | ✅ Yes | ❌ No | ❌ No | Remove AST node + update refs | **Direct** | Check for dead references |
| Move statement up/down | Reorder lines | ✅ Yes | ❌ No | ❌ No | Reorder in AST, check dependencies | **Direct** | Dependency validation |
| Wrap in condition | `x = 1` → `if flag: x = 1` | ⚠️ Partial | ❌ No | ❌ No | Wrap in If node, may need condition | **Template + LLM** | May need to determine condition |
| Extract to function | `a=1; b=2` → `setup()` | ❌ No | ✅ Yes | ❌ No | Create function stub + move code | **Template + Regenerate** | Need to determine signature |

### I. Control Flow Edits

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Add if statement (NL) | Add `if condition is met:` | ❌ No | ❌ No | ✅ Yes | LLM generates condition + body | **LLM** | Full generation needed |
| Add if statement (Python) | Add `if x > 0:` | ✅ Yes | ✅ Yes | ❌ No | Insert If node, may need body placeholder | **Direct + Placeholder** | Body might be `pass` initially |
| Add else clause | `if x:` → add `else:` | ✅ Yes | ✅ Yes | ❌ No | Add else node with placeholder | **Direct + Placeholder** | Body TBD |
| Add elif clause | Add `elif:` | ✅ Yes | ✅ Yes | ❌ No | Insert elif node | **Direct + Placeholder** | Condition + body TBD |
| Add for loop (NL) | `for each item in dataset` | ❌ No | ❌ No | ✅ Yes | LLM generates loop structure | **LLM** | Determine iteration target |
| Add for loop (Python) | `for i in range(10):` | ✅ Yes | ✅ Yes | ❌ No | Insert For node with placeholder body | **Direct + Placeholder** | Body TBD |
| Add while loop | `while condition:` | ⚠️ Partial | ✅ Yes | ❌ No | Insert While node, may need condition | **Direct + Placeholder** | Condition might be NL |
| Add try-except | Add exception handling | ⚠️ Partial | ✅ Yes | ❌ No | Insert Try node with placeholders | **Template + Placeholder** | Exception types TBD |

### J. Import and Dependencies

| Edit Type | Example | Direct Edit? | Requires Placeholder? | Requires Hole? | Python Transformation | Strategy | Notes |
|-----------|---------|--------------|----------------------|----------------|----------------------|----------|-------|
| Add import | `import pandas` | ✅ Yes | ❌ No | ❌ No | Insert import at top | **Direct** | Auto-organize imports |
| Remove import | Remove `import x` | ✅ Yes | ❌ No | ❌ No | Remove import if unused | **Direct** | Check usage first |
| Add from import | `from x import y` | ✅ Yes | ❌ No | ❌ No | Insert import | **Direct** | Position matters |
| Infer imports from NL | `use sklearn for ML` | ❌ No | ❌ No | ✅ Yes | LLM determines needed imports | **LLM** | Auto-import detection |

---

## Part 2: Python → Semiformal Edits

### K. Implementation Details (Transient - Usually Don't Propagate)

| Edit Type | Example | Propagate? | Strategy | Notes |
|-----------|---------|-----------|----------|-------|
| Variable rename (internal) | `temp` → `temporary` | ❌ Forbidden | None | Internal refactoring |
| Code refactoring | Extract helper function | ❌ Forbidden | None | Implementation detail |
| Add debug print | `print(debug_info)` | ❌ Forbidden | None | Temporary debugging |
| Optimize expression | `x = a + b + c` → `x = sum([a,b,c])` | ❌ Forbidden | None | Performance optimization |
| Add type hints | `def f(x)` → `def f(x: int)` | ⚠️ Optional | LLM summarize | May want to surface |
| Add docstring | Add function documentation | ⚠️ Optional | LLM summarize | May want to surface |
| Reorder imports | Sort imports | ❌ Forbidden | None | Stylistic change |

### L. Semantic Changes (Should Propagate)

| Edit Type | Example | Propagate? | Strategy | Notes |
|-----------|---------|-----------|----------|-------|
| Add new function | Define new function | ✅ Required | LLM summarize | Must add to spec |
| Change function logic | Modify algorithm | ✅ Required | LLM summarize | Semantic change |
| Add library dependency | Add new import for feature | ✅ Required | LLM summarize | Affects spec intent |
| Change parameter usage | Use param differently | ⚠️ Optional | LLM summarize | May indicate spec change |
| Add error handling | Add try-except block | ⚠️ Optional | LLM summarize | May be implementation detail |
| Change return value | Return different type/value | ✅ Required | LLM summarize | Breaks contract |

### M. Generated Region Edits (Within LLM-Generated Code)

| Edit Type | Example | Propagate? | Strategy | Notes |
|-----------|---------|-----------|----------|-------|
| Tweak constant | `test_size=0.2` → `test_size=0.3` | ❌ Forbidden | None | Fine-tuning parameter |
| Change library call | `pd.read_csv()` → `pd.read_excel()` | ⚠️ Optional | LLM summarize | May want to update NL |
| Add data validation | Add check before processing | ⚠️ Optional | LLM summarize | Enhancement |
| Fix bug | Correct implementation error | ❌ Forbidden | None | Bug fix in generated code |
| Improve efficiency | Use better algorithm | ❌ Forbidden | None | Optimization |

---

## Part 3: Edit Decision Matrix

### When to Use Each Strategy

| Strategy | Use When | Example Edits | Complexity | Accuracy |
|----------|----------|---------------|------------|----------|
| **Direct (AST)** | Edit is purely syntactic, no semantic ambiguity | Rename, operator change, literal change | Low | 100% |
| **Template** | Known pattern with fixed structure | Add stub function, create import | Low | 100% |
| **Placeholder** | Need to insert code but value is unknown | Add variable to LHS, add function arg | Medium | 50% (needs user input) |
| **Hole** | Explicitly marked area for LLM completion | `{}`, `{hint}`, NL expressions | Medium | 70-90% (LLM quality) |
| **LLM** | Semantic understanding needed | NL phrase changes, semantic edits | High | 70-90% (LLM quality) |
| **Regenerate** | Change affects entire function/block | Add parameter + update body, major logic change | High | 70-90% (LLM quality) |

### Decision Tree for Semiformal → Python

```
Edit detected in semiformal spec
  │
  ├─→ Is it a syntactic change? (rename, operator, literal)
  │   └─→ YES: Use Direct (AST manipulation)
  │
  ├─→ Does it involve NL text?
  │   ├─→ YES, NL phrase changed: Use LLM (regenerate)
  │   └─→ YES, NL added: Use Hole + LLM
  │
  ├─→ Does it add unknown values? (new var, new arg)
  │   └─→ YES: Use Placeholder + (LLM or user input)
  │
  ├─→ Does it change function signature?
  │   └─→ YES: Use Direct (signature) + Regenerate (body)
  │
  └─→ Is it a complex structural change?
      └─→ YES: Use LLM (full regeneration)
```

### Decision Tree for Python → Semiformal

```
Edit detected in generated Python
  │
  ├─→ Is it in a generated region (LLM-produced)?
  │   ├─→ YES, minor tweak: Don't propagate (Transient)
  │   └─→ YES, major change: Use LLM (summarize) + Ask user
  │
  ├─→ Is it a refactoring? (rename, reorder, optimize)
  │   └─→ YES: Don't propagate (Implementation detail)
  │
  ├─→ Does it add new functionality?
  │   └─→ YES: Use LLM (summarize) + Propagate (Required)
  │
  ├─→ Does it change semantics?
  │   └─→ YES: Use LLM (summarize) + Propagate (Required)
  │
  └─→ Is it a bug fix in generated code?
      └─→ YES: Don't propagate (Keep fix local)
```

---

## Part 4: Categorization Summary Tables

### By Translation Type

| Category | Direct | Placeholder | Hole | LLM | Regenerate | Count |
|----------|--------|-------------|------|-----|------------|-------|
| **Identifier Edits** | 7 | 3 | 0 | 2 | 5 | 17 |
| **Operator Edits** | 4 | 0 | 0 | 0 | 0 | 4 |
| **Literal Edits** | 4 | 0 | 0 | 0 | 0 | 4 |
| **Expression Edits** | 2 | 3 | 1 | 1 | 0 | 7 |
| **NL Edits** | 1 | 0 | 5 | 6 | 1 | 13 |
| **Statement Edits** | 3 | 1 | 1 | 2 | 1 | 8 |
| **Control Flow** | 2 | 6 | 2 | 3 | 0 | 13 |
| **Imports** | 3 | 0 | 1 | 1 | 0 | 5 |
| **TOTAL** | **26** | **13** | **10** | **15** | **7** | **71** |

### By Python Edit Type

| Python Edit Type | Count | % of Total |
|------------------|-------|------------|
| Pure Python AST manipulation | 26 | 36.6% |
| Requires placeholder/stub | 13 | 18.3% |
| Uses hole syntax `{}` | 10 | 14.1% |
| Requires LLM | 15 | 21.1% |
| Needs full regeneration | 7 | 9.9% |

### By Directionality

| Direction | Required Propagate | Optional Propagate | Forbidden Propagate | Total |
|-----------|-------------------|-------------------|---------------------|-------|
| **Semiformal → Python** | 71 | 0 | 0 | 71 |
| **Python → Semiformal** | 3 | 6 | 8 | 17 |

---

## Part 5: Examples with Code

### Example 1: Simple Rename (Direct)

**Semiformal Edit:**
```python
# Before
x = process_data(raw)

# After
result = process_data(raw)
```

**Python Transformation:**
```python
# Direct AST manipulation - rename all references
# Before
x = process_data(raw)
print(x)

# After
result = process_data(raw)
print(result)
```

**Strategy:** Direct (AST rename)
**Requires:** Nothing (100% accurate)

---

### Example 2: Add Variable to LHS (Placeholder)

**Semiformal Edit:**
```python
# Before
x = split_dataset()

# After
x, y = split_dataset()
```

**Python Transformation:**
```python
# Before
x = split_dataset()

# After (with placeholder)
x, y = split_dataset(), None  # Placeholder: need to determine y

# After (with LLM)
x, y = train_test_split(dataset, test_size=0.2)
```

**Strategy:** Direct + Placeholder + LLM
**Requires:** LLM to determine what `y` should be

---

### Example 3: Fill Hole (LLM)

**Semiformal Edit:**
```python
# Before
data = {}

# After
data = {use pandas to load CSV}
```

**Python Transformation:**
```python
# Before
data = None  # Hole marker

# After (LLM generated)
import pandas as pd
data = pd.read_csv('data.csv')
```

**Strategy:** Hole + LLM
**Requires:** LLM to interpret hint and generate code

---

### Example 4: Add Parameter (Direct + Regenerate)

**Semiformal Edit:**
```python
# Before
def process(data):
    ...

# After
def process(data, normalize):
    ...
```

**Python Transformation:**
```python
# Before
def process(data):
    result = data * 2
    return result

# After (signature updated directly, body regenerated)
def process(data, normalize):
    result = data * 2
    if normalize:
        result = result / result.max()  # LLM adds this
    return result
```

**Strategy:** Direct (signature) + Regenerate (body)
**Requires:** LLM to regenerate body using new parameter

---

### Example 5: Change NL Phrase (LLM)

**Semiformal Edit:**
```python
# Before
data = load dataset

# After
data = load and preprocess dataset
```

**Python Transformation:**
```python
# Before (generated)
import pandas as pd
data = pd.read_csv('dataset.csv')

# After (regenerated)
import pandas as pd
data = pd.read_csv('dataset.csv')
data = data.dropna()  # Preprocessing added
data = data.fillna(0)
```

**Strategy:** LLM (full regeneration)
**Requires:** LLM to interpret "preprocess" in context

---

### Example 6: Python → Semiformal (Transient)

**Python Edit:**
```python
# User changes
X_train, X_test = train_test_split(dataset, test_size=0.2)
# to
X_train, X_test = train_test_split(dataset, test_size=0.3, random_state=42)
```

**Semiformal Update:**
```python
# Before
X_train, X_test = split dataset into training and test

# After (no change - transient edit)
X_train, X_test = split dataset into training and test
```

**Strategy:** Don't propagate (transient parameter tuning)
**Requires:** Nothing

---

### Example 7: Python → Semiformal (Semantic Change)

**Python Edit:**
```python
# User adds
def validate_data(data):
    return data[data > 0]

result = validate_data(process_data(raw))
```

**Semiformal Update:**
```python
# Before
result = process_data(raw)

# After (LLM summarizes change)
validated = remove negative values from data
result = process_data(validated)
```

**Strategy:** LLM summarize + Propagate
**Requires:** LLM to create NL summary of new functionality