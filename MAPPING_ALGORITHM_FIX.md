# Code Mapping Algorithm Fix

## Problem

The original mapping algorithm was oversimplified and had critical flaws when mapping semiformal code nodes to generated Python code:

### Issues with Original Algorithm

1. **First-match bias**: Found the FIRST occurrence of `var_name =` without considering semantic correctness
2. **No context awareness**: Didn't distinguish between:
   - Module-level code vs code inside function definitions
   - Example/intermediate code vs actual implementation
3. **No dependency matching**: Couldn't determine which of multiple implementations was correct
4. **Oversimplification**: Assumed one semiformal line maps to one generated line

### Real-World Failure Example

Given semiformal code:
```python
result = load the dataset and process it
output = transform(result)
x, y = {split data into train and test}
```

And LLM-generated code with multiple implementations:
```python
# ... imports and function definitions ...

# Example code:
output = result.apply(lambda x: x * 2)
x, y = train_test_split(result, test_size=0.2)

# Actual implementation:
output = transform(result)
x, y = train_test_split(output, test_size=0.2, random_state=42)
```

The old algorithm would:
- Map `output` → `output = result.apply(...)` ❌ (wrong - example code)
- Map `x` → `x, y = train_test_split(result, ...)` ❌ (wrong - uses 'result' not 'output')

## Solution

Implemented a robust AST-based mapping algorithm in `backend/code_mapper.py` with:

### Key Features

1. **AST-based analysis**: Parses generated code to understand structure
2. **Context filtering**: Distinguishes module-level statements from function internals
3. **Dependency matching**: Scores candidates based on variable dependencies in RHS
4. **Execution order awareness**: Prefers later implementations (LLMs often generate examples first)
5. **Multiple implementation handling**: Correctly disambiguates when variable appears multiple times

### Algorithm Steps

1. Parse generated code into AST
2. Extract all statements with metadata (assigned vars, referenced vars, execution order)
3. Filter to module-level statements (for variable assignments)
4. For each semiformal node:
   - Find all candidate statements that assign to the variable
   - Extract expected dependencies from semiformal spec
   - Score each candidate based on dependency matching
   - Prefer highest scoring match, with execution order as tiebreaker

### Scoring System

Dependency match score:
- Jaccard similarity between actual and expected dependencies
- Bonus for exact match (+1.0)
- Bonus for having all expected deps (+0.5)
- Execution order used as tiebreaker when scores equal

## Results

With the new algorithm:
- `output` → `output = transform(result)` ✅ (correct - matches dependency 'transform')
- `x` → `x, y = train_test_split(output, ...)` ✅ (correct - matches dependency 'output', later execution)

## Integration

The new algorithm is integrated into `backend/diff_generator.py`:
- `DiffGenerator._generate_implementations()` now uses `extract_implementations_robust()`
- Maintains backward compatibility
- No changes needed to public APIs

## Testing

Run `test_user_mapping_issue.py` to see comparison between old and new algorithms:
```bash
python test_user_mapping_issue.py
```

## Future Improvements

1. **Multi-statement mappings**: Map "load and process" to multiple consecutive statements
2. **Comment-based hints**: Use code comments to improve matching
3. **Control flow awareness**: Better handling of conditionals and loops
4. **Cross-function tracking**: Track variable flow across function calls
