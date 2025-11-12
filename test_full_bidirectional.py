#!/usr/bin/env python3
"""
Full bidirectional workflow integration test.
Tests the complete cycle:
1. Spec -> Code (GET)
2. Code edits (user changes)
3. Code -> Spec (PUT)
4. Spec edits (user changes)
5. Spec -> Code (GET with structural transformation)
"""

import sys
sys.path.insert(0, 'backend')

from backend.ast_parser import parse_semiformal
from backend.skeleton_generator import generate_skeleton
from backend.ir_sync import IRSync
from backend.ir import NodeStatus

print("=" * 70)
print("FULL BIDIRECTIONAL WORKFLOW TEST")
print("=" * 70)

# Initialize sync without LLM
sync = IRSync(use_llm=False)

# ============================================================================
# STEP 1: Initial Spec -> Code (GET Direction)
# ============================================================================
print(f"\n{'='*70}")
print("STEP 1: Spec -> Code (GET Direction)")
print(f"{'='*70}")

spec_v1 = """result = process_data(raw_input)

x = split dataset into training and test sets

output = transform(x)

print(result, x, output)
"""

print(f"\nInitial Spec:\n{spec_v1}")

# Parse and set IR
ir1 = parse_semiformal(spec_v1)
sync.set_ir(ir1)

# Simulate LLM generation
for node in ir1.nodes.values():
    if node.name == "x" and "split dataset" in node.spec_text.lower():
        node.code_text = "x = (x_train, x_test)"
        node.status = NodeStatus.GENERATED

code_v1 = generate_skeleton(ir1)
print(f"Generated Code:\n{code_v1}")

# Verify
if "x = (x_train, x_test)" in code_v1:
    print("\n✓ STEP 1 PASSED: Code generated from spec")
else:
    print("\n✗ STEP 1 FAILED")
    sys.exit(1)

# ============================================================================
# STEP 2: User Edits Code -> Spec (PUT Direction)
# ============================================================================
print(f"\n{'='*70}")
print("STEP 2: Code Edit -> Spec (PUT Direction)")
print(f"{'='*70}")

# User changes code: x = (x_train, x_test) -> x, y = train_test_split(...)
code_v2 = code_v1.replace(
    "x = (x_train, x_test)",
    "x, y = train_test_split(dataset, test_size=0.2)"
)

print(f"\nUser Edits Code:\n{code_v2}")

# Sync back to spec
result = sync.sync_code_change(spec_v1, code_v1, code_v2)
spec_v2 = result.updated_source

print(f"\nUpdated Spec:\n{spec_v2}")

# Verify node is USER_EDITED
x_node = [n for n in sync.ir.nodes.values() if n.name == "x"][0]
if x_node.status.value == 'user_edited' and "train_test_split" in x_node.code_text:
    print("\n✓ STEP 2 PASSED: Code edits tracked in IR as USER_EDITED")
else:
    print(f"\n✗ STEP 2 FAILED: Node status={x_node.status.value}")
    sys.exit(1)

# ============================================================================
# STEP 3: User Edits Spec -> Code (GET with Structural Transform)
# ============================================================================
print(f"\n{'='*70}")
print("STEP 3: Spec Edit -> Code (GET with Structural Transform)")
print(f"{'='*70}")

# User edits spec: x,y = ... (adds y to LHS)
# This should trigger structural transformation on the code
spec_v3 = spec_v2.replace(
    "x = split dataset into training and test sets",
    "x,y,z = split dataset into training, validation, and test sets"
)

print(f"\nUser Edits Spec (LHS change: x,y -> x,y,z):\n{spec_v3}")

# Sync spec change (should apply structural transformation)
sync.merge_and_transform(spec_v3)
code_v3 = generate_skeleton(sync.ir)

print(f"\nUpdated Code:\n{code_v3}")

# Verify structural transformation applied
if "(x, y, z) =" in code_v3 or "x, y, z =" in code_v3 or "x,y,z =" in code_v3:
    if "train_test_split" in code_v3:
        print("\n✓ STEP 3 PASSED: LHS structural transformation applied, user code preserved")
    else:
        print("\n✗ STEP 3 FAILED: User code lost")
        sys.exit(1)
else:
    print(f"\n✗ STEP 3 FAILED: LHS not transformed correctly")
    print(f"  Expected 'x, y, z =' but got:")
    for line in code_v3.split('\n'):
        if 'train_test_split' in line:
            print(f"    {line}")
    sys.exit(1)

# ============================================================================
# STEP 4: Another Code Edit -> Spec (PUT)
# ============================================================================
print(f"\n{'='*70}")
print("STEP 4: Another Code Edit -> Spec (PUT)")
print(f"{'='*70}")

# User refines the implementation in code
code_v4 = code_v3.replace(
    "train_test_split(dataset, test_size=0.2)",
    "train_test_split(dataset, test_size=0.15, val_size=0.15, random_state=42)"
)

print(f"\nUser Refines Code:\n{code_v4}")

# Sync back to spec
result = sync.sync_code_change(spec_v3, code_v3, code_v4)
spec_v4 = result.updated_source

print(f"\nUpdated Spec:\n{spec_v4}")

# Verify
x_node_final = [n for n in sync.ir.nodes.values() if n.name == "x"][0]
if "random_state=42" in x_node_final.code_text:
    print("\n✓ STEP 4 PASSED: Code refinements tracked in IR")
else:
    print(f"\n✗ STEP 4 FAILED")
    sys.exit(1)

# ============================================================================
# FINAL VERIFICATION
# ============================================================================
print(f"\n{'='*70}")
print("FINAL VERIFICATION")
print(f"{'='*70}")

checks = [
    ("Spec tracked through multiple edits", spec_v4 is not None),
    ("Code tracked through multiple edits", code_v4 is not None),
    ("IR maintains state", sync.ir is not None),
    ("Node status correctly updated", x_node_final.status.value == 'user_edited'),
    ("User code preserved through spec edits", "train_test_split" in x_node_final.code_text),
    ("Structural transformations applied", "x, y, z" in code_v4 or "(x, y, z)" in code_v4),
]

all_passed = True
for check_name, check_result in checks:
    if check_result:
        print(f"  ✓ {check_name}")
    else:
        print(f"  ✗ {check_name}")
        all_passed = False

print("\n" + "=" * 70)
if all_passed:
    print("✅ FULL BIDIRECTIONAL WORKFLOW TEST PASSED")
    print("   - Spec -> Code (GET) ✓")
    print("   - Code -> Spec (PUT) ✓")
    print("   - Structural transformations ✓")
    print("   - User code preservation ✓")
else:
    print("❌ FULL BIDIRECTIONAL WORKFLOW TEST FAILED")
    sys.exit(1)
print("=" * 70)
