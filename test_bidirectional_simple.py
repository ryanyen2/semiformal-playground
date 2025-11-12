#!/usr/bin/env python3
"""
Simple test for bidirectional sync without OpenAI dependency.
Tests structural transformations only.
"""

import sys
sys.path.insert(0, 'backend')

from backend.ast_parser import parse_semiformal
from backend.skeleton_generator import generate_skeleton
from backend.ir_sync import IRSync
from backend.ir import NodeStatus

print("=" * 70)
print("BIDIRECTIONAL SYNC TEST (No LLM)")
print("=" * 70)

# Initialize sync without LLM
sync = IRSync(use_llm=False)

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

# Step 2: Manually simulate LLM generation (without calling OpenAI)
print("\n--- Step 2: Manually Set Generated Code (Simulating LLM) ---")
for node in ir1.nodes.values():
    if node.name == "x" and "split dataset" in node.spec_text.lower():
        # Simulate LLM generated this:
        node.code_text = "x = (x_train, x_test)"
        node.status = NodeStatus.GENERATED
        print(f"Set generated code for '{node.name}': {node.code_text}")
        print(f"  Status: {node.status.value}")

# Regenerate skeleton with generated code
skeleton2 = generate_skeleton(ir1)
print(f"\nSkeleton with Generated Code:\n{skeleton2}")

# Verify the generated code is present
if "x_train" in skeleton2:
    print("\n✓ Generated code is present in skeleton")
else:
    print("\n✗ Generated code MISSING from skeleton")

# Step 3: User edits spec (x -> x,y) - test structural transformation
spec_v2 = """result = process_data(raw_input)

x,y = split dataset into training and test sets

output = transform(x)

print(result, x, output)
"""

print(f"\n--- Step 3: User Edits Spec (x -> x,y) ---\n{spec_v2}")

# Use merge_and_transform (no LLM call)
sync.merge_and_transform(spec_v2)
ir2 = sync.ir

# Generate skeleton
skeleton3 = generate_skeleton(ir2)

print(f"\nSkeleton After Edit:\n{skeleton3}")

# Verification
print("\n--- Verification ---")

success = True

# Check if LHS was transformed correctly
if "(x, y) =" in skeleton3 or "x, y =" in skeleton3 or "x,y =" in skeleton3:
    print("✓ LHS transformed from 'x =' to tuple assignment")
else:
    print("✗ LHS not transformed correctly")
    print(f"   Looking for 'x, y =' or '(x, y) =' but found:")
    for line in skeleton3.split('\n'):
        if 'x' in line and '=' in line and 'split' not in line.lower():
            print(f"     {line}")
    success = False

# Check if generated code was preserved (not replaced with placeholder)
if "x_train" in skeleton3:
    print("✓ Generated code preserved (contains x_train)")
else:
    print("✗ Generated code LOST - reverted to placeholder")
    success = False

# Check if it didn't revert to placeholder
if "x = ..." in skeleton3 and "x, y" not in skeleton3:
    print("✗ Reverted to placeholder instead of preserving generated code")
    success = False
else:
    print("✓ Did not revert to placeholder")

# Check if it's valid Python
print("\n--- Python Validity Check ---")
try:
    import ast
    ast.parse(skeleton3)
    print("✓ Generated code is valid Python")
except SyntaxError as e:
    print(f"✗ Generated code has syntax errors: {e}")
    success = False

print("\n" + "=" * 70)
if success:
    print("✅ ALL TESTS PASSED")
else:
    print("❌ SOME TESTS FAILED")
print("=" * 70)
