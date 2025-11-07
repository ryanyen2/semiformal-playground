#!/usr/bin/env python3
"""
Test LHS change transformation (x -> x,y).

This tests the new systematic approach with AST-level mapping and
structural transformations.
"""

import sys
sys.path.insert(0, 'backend')

from backend.ast_parser import parse_semiformal
from backend.skeleton_generator import generate_skeleton
from backend.ir import NodeStatus
from backend.ir_sync import IRSync

print("=" * 70)
print("TEST: LHS Change Transformation (x -> x,y)")
print("=" * 70)

# Initialize sync
sync = IRSync()

# Step 1: Initial spec
spec_v1 = """result = process_data(raw_input)

x = split dataset into training and test sets

output = transform(x)

print(result, x, output)
"""

print(f"\n--- Step 1: Initial Spec ---\n{spec_v1}")

# Parse and generate skeleton
ir1 = parse_semiformal(spec_v1)
sync.set_ir(ir1)
skeleton1 = generate_skeleton(ir1)

print(f"Generated Skeleton:\n{skeleton1}")

# Step 2: Simulate LLM generation by setting generated code
print("\n--- Step 2: Simulate LLM Generation ---")
for node in ir1.nodes.values():
    if node.name == "x" and node.node_type.value == "nl_expression":
        node.code_text = "x = (x_train, x_test)"
        node.status = NodeStatus.GENERATED
        print(f"Generated code for {node.name}: {node.code_text}")

# Regenerate with the updated IR
skeleton2 = generate_skeleton(ir1)
print(f"\nSkeleton with Generated Code:\n{skeleton2}")

# Step 3: User edits spec (x -> x,y)
spec_v2 = """result = process_data(raw_input)

x,y = split dataset into training and test sets

output = transform(x)

print(result, x, output)
"""

print(f"\n--- Step 3: User Edits Spec (x -> x,y) ---\n{spec_v2}")

# Sync the change
result = sync.sync_spec_change(spec_v1, spec_v2)

print(f"Sync Result Message: {result.message}")
print(f"\n Final Generated Code:\n{result.updated_source}")

# Verification
print("\n--- Verification ---")

# Check if LHS was transformed correctly
if "x, y =" in result.updated_source or "x,y =" in result.updated_source or "(x, y) =" in result.updated_source:
    print("✓ LHS transformed from 'x =' to 'x, y =' (or 'x,y =')")
else:
    print("✗ LHS not transformed correctly")
    print(f"   Looking for 'x, y =' or '(x, y) =' in:\n{result.updated_source}")

# Check if generated code was preserved (not replaced with placeholder)
if "x_train" in result.updated_source or "(x_train, x_test)" in result.updated_source:
    print("✓ Generated code preserved (contains x_train)")
else:
    print("✗ Generated code lost")

# Check if it's NOT just a placeholder
if result.updated_source.count("x = ...") > 0 and "x, y =" not in result.updated_source:
    print("✗ Reverted to placeholder instead of preserving generated code")
else:
    print("✓ Did not revert to placeholder")

# Check if it's valid Python
print("\n--- Python Validity Check ---")
try:
    import ast
    ast.parse(result.updated_source)
    print("✓ Generated code is valid Python")
except SyntaxError as e:
    print(f"✗ Generated code has syntax errors: {e}")

print("\n" + "=" * 70)

