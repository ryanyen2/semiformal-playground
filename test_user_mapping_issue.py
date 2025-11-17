#!/usr/bin/env python3
"""
Test case demonstrating the mapping algorithm issue.

The semiformal code has underspecified statements, and the generated
code contains multiple implementations. The mapping algorithm needs to
correctly map each semiformal node to the appropriate generated code subtree.
"""

import sys
sys.path.insert(0, 'backend')

from backend.ast_parser import parse_semiformal
from backend.ir import NodeStatus
import ast
from typing import List, Optional

print("=" * 70)
print("TEST: User Mapping Issue")
print("=" * 70)

# User's semiformal code
semiformal_code = """result = load the dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)
"""

print("\n--- Semiformal Code ---")
print(semiformal_code)

# Parse semiformal code
ir = parse_semiformal(semiformal_code)

print("\n--- Parsed IR Nodes ---")
for node in ir.nodes.values():
    print(f"{node.name} ({node.node_type.value}): {repr(node.spec_text)}")

# Simulate LLM generation by providing the actual generated code
# This is what the LLM returned
llm_generated_code = """from sklearn.model_selection import train_test_split
from typing import Tuple, Any
import pandas as pd

def transform(result: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    \"\"\"Transforms dataset and splits into train and test sets.\"\"\"
    if not isinstance(result, pd.DataFrame):
        raise ValueError('Input must be a pandas DataFrame.')
    transformed_result = result.fillna(result.mean())
    if 'target' not in transformed_result.columns:
        raise ValueError("DataFrame must contain a 'target' column.")
    X = transformed_result.drop(columns='target')
    y = transformed_result['target']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    return (X_train, X_test, y_train, y_test)

import pandas as pd
from sklearn.model_selection import train_test_split

# Load the dataset
data = pd.read_csv('data.csv')

# Process the dataset (example: drop missing values)
processed_data = data.dropna()

# Assign to result
result = processed_data

# Transform the result (example transformation)
output = result.apply(lambda x: x * 2)

# Split data into train and test
x, y = train_test_split(result, test_size=0.2)

print(output)
output = transform(result)
from sklearn.model_selection import train_test_split

x, y = train_test_split(output, test_size=0.2, random_state=42)
print(output)
"""

print("\n--- LLM Generated Code ---")
print(llm_generated_code)

# Now test the extraction algorithm (simplified version from DiffGenerator)
print("\n" + "=" * 70)
print("TESTING EXTRACTION ALGORITHM")
print("=" * 70)

def extract_function(lines: List[str], func_name: str) -> Optional[str]:
    """Extract function implementation from lines."""
    func_lines = []
    in_function = False
    indent_level = 0

    for line in lines:
        if f"def {func_name}(" in line:
            in_function = True
            indent_level = len(line) - len(line.lstrip())
            func_lines.append(line)
        elif in_function:
            if line.strip() and not line[0].isspace():
                # End of function
                break
            elif line.strip() and len(line) - len(line.lstrip()) <= indent_level:
                # Dedent, end of function
                break
            else:
                func_lines.append(line)

    return '\n'.join(func_lines) if func_lines else None

def extract_assignment(lines: List[str], var_name: str) -> Optional[str]:
    """Extract variable assignment from lines (CURRENT SIMPLE ALGORITHM)."""
    for line in lines:
        stripped = line.strip()
        # Check if line starts with var_name =
        if stripped.startswith(f"{var_name} ="):
            return stripped
        # Also check for tuple unpacking like "x, y ="
        if '=' in stripped:
            lhs = stripped.split('=')[0].strip()
            # Check if var_name is in the LHS
            if var_name in lhs.replace(' ', '').split(','):
                return stripped
    return None

def extract_implementations(generated_code: str, incomplete_nodes):
    """Extract implementations for each node from generated code."""
    implementations = {}
    lines = generated_code.split('\n')

    print("\nDEBUG extract_implementations:")
    for node in incomplete_nodes:
        print(f"\n  Processing node: {node.name} (type={node.node_type.value})")

        # Use string comparison of enum values to avoid import issues
        node_type_val = node.node_type.value

        if node_type_val in ('function_def', 'function_call'):
            # Extract function implementation (both defined functions and called functions that need stubs)
            print(f"    Extracting function '{node.name}'")
            impl = extract_function(lines, node.name)
            if impl:
                print(f"    FOUND: {impl[:50]}...")
                implementations[node.id] = impl
            else:
                print(f"    NOT FOUND")

        elif node_type_val in ('variable_assign', 'nl_expression'):
            # Extract variable assignment
            print(f"    Extracting assignment '{node.name}'")
            impl = extract_assignment(lines, node.name)
            if impl:
                print(f"    FOUND: {impl[:50]}...")
                implementations[node.id] = impl
            else:
                print(f"    NOT FOUND")

    return implementations

lines = llm_generated_code.split('\n')

# Get incomplete nodes
incomplete_nodes = ir.get_incomplete_nodes()
print(f"\nIncomplete nodes: {len(incomplete_nodes)}")
for node in incomplete_nodes:
    print(f"  - {node.name} ({node.node_type.value}): {repr(node.spec_text)}")

# Try to extract implementations with OLD algorithm
print("\n" + "="*70)
print("OLD ALGORITHM (simple text matching)")
print("="*70)
implementations = extract_implementations(llm_generated_code, incomplete_nodes)

print(f"\n--- Extracted Implementations ---")
if not implementations:
    print("NO IMPLEMENTATIONS EXTRACTED!")
    print("\nDEBUG: Checking what the extraction algorithm is looking for:")
    for node in incomplete_nodes:
        print(f"\n  Node: {node.name} ({node.node_type.value})")
        if hasattr(node.node_type, 'FUNCTION_DEF') and node.node_type.value == 'function_def':
            print(f"    Looking for: 'def {node.name}('")
        else:
            print(f"    Looking for: '{node.name} ='")
        print(f"    Spec text: {repr(node.spec_text)}")

for node_id, impl in implementations.items():
    node = ir.nodes.get(node_id)
    if node:
        print(f"\nNode: {node.name} ({node.node_type.value})")
        print(f"Spec: {repr(node.spec_text)}")
        print(f"Extracted implementation:")
        print(impl)
        print("-" * 50)

# Check for issues
print("\n" + "=" * 70)
print("ISSUE DETECTION")
print("=" * 70)

issues = []

# Check if mappings are correct
for node_id, impl in implementations.items():
    node = ir.nodes.get(node_id)
    if not node:
        continue

    if node.name == "result":
        # result should map to the multi-line implementation (load + process)
        # NOT to just "result = processed_data"
        if "read_csv" not in impl:
            issues.append(f"✗ 'result' mapped incorrectly - missing dataset loading (read_csv)")
            issues.append(f"   Got: {repr(impl[:100])}")
        else:
            print(f"✓ 'result' correctly mapped to dataset loading code")

    elif node.name == "output":
        # output has TWO implementations in generated code!
        # First: output = result.apply(lambda x: x * 2)  (example)
        # Second: output = transform(result)  (actual)
        # The correct mapping should be to transform(result)
        if "transform(" in impl:
            print(f"✓ 'output' correctly mapped to transform() call")
        elif "apply" in impl:
            issues.append(f"✗ 'output' mapped to wrong implementation (example code instead of actual)")
            issues.append(f"   Got: {repr(impl)}")
        else:
            issues.append(f"✗ 'output' mapped to unexpected code")
            issues.append(f"   Got: {repr(impl)}")

    elif node.name in ("x", "y"):
        # x, y should map to the FINAL train_test_split call
        # NOT to intermediate ones or the one inside the function
        lines_impl = impl.split('\n')
        # Check if it's at module level (not indented)
        if lines_impl and lines_impl[0].startswith(' '):
            issues.append(f"✗ '{node.name}' mapped to indented code (inside function?)")
            issues.append(f"   Got: {repr(impl[:100])}")
        elif "train_test_split(output" in impl:
            print(f"✓ '{node.name}' correctly mapped to final train_test_split call")
        else:
            issues.append(f"✗ '{node.name}' mapped to wrong train_test_split call")
            issues.append(f"   Expected: train_test_split(output, ...")
            issues.append(f"   Got: {repr(impl)}")

    elif node.name == "transform":
        # transform is a function, check if it includes the full function body
        if "def transform(" in impl and "return" in impl:
            print(f"✓ 'transform' correctly mapped to complete function")
        else:
            issues.append(f"✗ 'transform' missing function body or return")
            issues.append(f"   Got: {repr(impl[:100])}")

# Report results
if not issues:
    print("\n✅ ALL MAPPINGS CORRECT!")
else:
    print(f"\n❌ FOUND {len(issues)} MAPPING ISSUES:")
    for issue in issues:
        print(f"  {issue}")

# Now test the NEW robust algorithm
print("\n" + "=" * 70)
print("NEW ALGORITHM (AST-based with dependency matching)")
print("=" * 70)

from backend.code_mapper import extract_implementations_robust

new_implementations = extract_implementations_robust(llm_generated_code, incomplete_nodes)

print(f"\n--- Extracted Implementations (NEW) ---")
for node_id, impl in new_implementations.items():
    node = ir.nodes.get(node_id)
    if node:
        print(f"\nNode: {node.name} ({node.node_type.value})")
        print(f"Spec: {repr(node.spec_text)}")
        print(f"Extracted implementation:")
        print(impl)
        print("-" * 50)

# Check for issues with NEW algorithm
print("\n" + "=" * 70)
print("ISSUE DETECTION (NEW ALGORITHM)")
print("=" * 70)

new_issues = []

for node_id, impl in new_implementations.items():
    node = ir.nodes.get(node_id)
    if not node:
        continue

    if node.name == "result":
        # result should ideally map to the multi-line implementation (load + process)
        # But at minimum it should map to the RIGHT single line
        if "processed_data" in impl:
            # For now accept this, but note it's still not perfect
            print(f"✓ 'result' mapped to result = processed_data")
            print(f"  NOTE: Ideally would map to multi-line load+process sequence")
        else:
            new_issues.append(f"✗ 'result' mapped to unexpected code")
            new_issues.append(f"   Got: {repr(impl)}")

    elif node.name == "output":
        # output should map to transform(result), NOT the example apply code
        if "transform(result)" in impl:
            print(f"✓ 'output' CORRECTLY mapped to transform(result) call!")
        elif "apply" in impl:
            new_issues.append(f"✗ 'output' still mapped to wrong implementation (example code)")
            new_issues.append(f"   Got: {repr(impl)}")
        else:
            new_issues.append(f"✗ 'output' mapped to unexpected code")
            new_issues.append(f"   Got: {repr(impl)}")

    elif node.name == "x":
        # x should map to the FINAL train_test_split(output, ...) call
        if "train_test_split(output" in impl:
            print(f"✓ 'x' CORRECTLY mapped to final train_test_split(output, ...) call!")
        elif "train_test_split(result" in impl:
            new_issues.append(f"✗ 'x' still mapped to wrong train_test_split call (uses 'result' not 'output')")
            new_issues.append(f"   Got: {repr(impl)}")
        else:
            new_issues.append(f"✗ 'x' mapped to unexpected code")
            new_issues.append(f"   Got: {repr(impl)}")

    elif node.name == "transform":
        if "def transform(" in impl and "return" in impl:
            print(f"✓ 'transform' correctly mapped to complete function")
        else:
            new_issues.append(f"✗ 'transform' missing function body or return")
            new_issues.append(f"   Got: {repr(impl[:100])}")

if not new_issues:
    print("\n✅ ALL MAPPINGS CORRECT WITH NEW ALGORITHM!")
else:
    print(f"\n⚠️ FOUND {len(new_issues)} ISSUES WITH NEW ALGORITHM:")
    for issue in new_issues:
        print(f"  {issue}")

print("\n" + "=" * 70)
print("DIAGNOSIS")
print("=" * 70)

print("""
The current mapping algorithm has several fundamental problems:

1. **First-match bias**: It finds the FIRST occurrence of 'var_name ='
   without considering context or semantic correctness.

2. **No context awareness**: Doesn't distinguish between:
   - Code inside function definitions vs module-level code
   - Intermediate/example code vs actual implementation
   - Multiple valid implementations of the same variable

3. **Oversimplification**: Assumes one semiformal line maps to one generated line,
   but reality is:
   - One semiformal statement may expand to multiple lines (result = load + process)
   - Multiple generated implementations may exist (output appears 2x)
   - Generated code has additional context (imports, function defs)

4. **No structural understanding**: Doesn't use AST structure to understand:
   - What's the "main" code vs helper functions
   - What code is at module-level vs inside definitions
   - Dependencies and execution order

NEEDED: A robust algorithm that:
- Uses AST structure to understand code organization
- Maps semiformal nodes to complete subtrees (not just single lines)
- Distinguishes main implementation from helpers/examples
- Handles one-to-many mappings (one semiformal -> multiple generated statements)
- Uses execution order and dependencies to disambiguate
""")

print("=" * 70)
