# Fix Summary: Function Body Stripping for Unbiased LLM Code Generation

## Problem

When semiformal stub functions are sent to the LLM for regeneration, their existing bodies (even if throwaway implementations) biased the LLM toward generating similar code rather than generating fresh, optimal implementations based on new context.

### Example Scenario

When a user adds `data = load_dataset('iris.csv')` and the DAG determines that `preprocessing(data)` needs regeneration, the LLM was receiving:

```python
def preprocessing(data):  #> preprocessing
    # Old throwaway implementation with prior assumptions
    data = pd.DataFrame(data)
    numeric_cols = data.select_dtypes(include=['number']).columns.tolist()
    ...
```

This caused the LLM to generate code biased toward the old implementation instead of reasoning fresh from:
- The new data source ('iris.csv')
- Updated dependencies
- Current data flow context

## Solution

Implemented a comprehensive function body stripping mechanism that:

1. **Identifies functions requiring regeneration** using DAG analysis
2. **Strips function bodies** while preserving signatures
3. **Provides clear instructions** to LLM about regeneration expectations

## Implementation Details

### 1. Function Body Stripping (`generator.py`)

Added `strip_function_bodies_for_regeneration()` function that:
- Works with both valid Python and semiformal code (NL phrases, holes, etc.)
- Uses regex-based line scanning (not AST) to handle semiformal syntax
- Preserves function signatures with anchor comments
- Replaces bodies with `pass  # body omitted - will be regenerated`
- Handles proper indentation

### 2. Function Identification (`generator.py`)

Added `_identify_functions_to_regenerate()` method that:
- Analyzes DAG's `update_spec.nodes_to_regenerate`
- Identifies function calls that need regeneration
- Distinguishes user-defined functions from builtins/libraries
- Returns set of function names to strip

### 3. Integration in Generation Pipeline (`generator.py`)

Modified `generate_with_mapping()` to:
1. Build data flow graph and detect changes
2. Compute update specification via DAG analysis
3. **Identify functions to strip** based on regeneration needs
4. **Strip function bodies** from semiformal code
5. Annotate stripped code with semantic anchors
6. Send to LLM with clear context

### 4. Enhanced LLM Prompts (`llm_service.py`)

Updated system prompt to emphasize:
- Recognize stripped functions (`pass  # body omitted - will be regenerated`)
- Generate COMPLETE NEW implementations from scratch
- DO NOT assume or copy from prior implementations
- Reason based on: function name, parameters, dependencies, data flow

Added runtime prompt section when functions are stripped:
```
## CRITICAL: Function Body Regeneration

**IMPORTANT**: Some functions have their bodies replaced with `pass` statements.
This is INTENTIONAL. These functions require COMPLETE REGENERATION based on new context.

For functions with `pass  # body omitted - will be regenerated`:
- DO NOT assume or copy from any prior implementation
- Generate FRESH, COMPLETE implementations from scratch
- Reason based on: function name, parameters, dependencies, and data flow context
- Consider what changed (data source, dependencies, signatures) and adapt accordingly
```

## Key Benefits

1. **Unbiased Generation**: LLM generates fresh code based on current context, not throwaway stubs
2. **Better Adaptation**: Functions adapt properly to new data sources, parameters, and dependencies
3. **Generalizable**: Works for any function requiring regeneration, not just specific use cases
4. **No Breaking Changes**: Existing functionality preserved, only adds stripping when needed
5. **Clear Communication**: Explicit markers and instructions guide LLM behavior

## Testing

Created comprehensive test suite (`test_function_stripping.py`) verifying:
- ✅ Simple function body stripping
- ✅ Selective stripping (multiple functions, strip only some)
- ✅ Semiformal code with anchor comments
- ✅ Empty set handling (no stripping needed)

All tests pass successfully.

## Example Output

**Before (with throwaway implementation):**
```python
def preprocessing(data):  #> preprocessing
    # Old implementation based on different assumptions
    data = pd.DataFrame(data)
    numeric_cols = data.select_dtypes(include=['number']).columns.tolist()
    categorical_cols = data.select_dtypes(include=['object']).columns.tolist()
    return data

data = load_dataset('iris.csv')  #> data; load_dataset
df = preprocessing(data)  #> df; preprocessing; data
```

**After (stripped for regeneration):**
```python
def preprocessing(data):  #> preprocessing
    pass  # body omitted - will be regenerated

data = load_dataset('iris.csv')  #> data; load_dataset
df = preprocessing(data)  #> df; preprocessing; data
```

Now the LLM will generate a fresh `preprocessing` implementation specifically adapted to the Iris dataset, without being biased by any prior code.

## Files Modified

1. **`backend/generator.py`**
   - Enhanced `strip_function_bodies_for_regeneration()` with regex-based scanning
   - Added `_identify_functions_to_regenerate()` method
   - Added `_is_user_defined_function()` helper
   - Integrated stripping into `generate_with_mapping()` pipeline
   - Added `NodeKind` import from dataflow_graph

2. **`backend/llm_service.py`**
   - Updated `SYSTEM_PROMPT` with stripped function guidance
   - Added runtime prompt section for function regeneration
   - Enhanced instructions for handling stripped functions

## Conclusion

This fix ensures that semiformal stub functions don't bias LLM generation. By stripping function bodies before sending to the LLM and providing clear instructions, we enable fresh, context-aware code generation that adapts properly to changes in data sources, dependencies, and function signatures.

The implementation is:
- **Robust**: Handles both valid Python and semiformal syntax
- **Generalizable**: Works for any migration scenario, not hardcoded
- **Well-tested**: Comprehensive test coverage
- **Non-breaking**: Only activates when functions need regeneration
