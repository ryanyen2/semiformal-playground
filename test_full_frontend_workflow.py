#!/usr/bin/env python3
"""
Test the COMPLETE frontend workflow with session management.

This simulates what happens when the user:
1. Types spec
2. Frontend calls /skeleton (continuous)
3. User hits Cmd+S
4. Frontend calls /generate
5. User edits spec again  
6. Frontend calls /skeleton again
"""

import sys
sys.path.insert(0, 'backend')

from backend.ast_parser import parse_semiformal
from backend.skeleton_generator import generate_skeleton
from backend.diff_generator import DiffGenerator
from backend.ir_sync import AutoSync

print("=" * 70)
print("FULL FRONTEND WORKFLOW TEST")
print("=" * 70)

# Simulate session (like the backend maintains)
SESSION_ID = "test-session"
sessions = {}

def get_or_create_session(session_id):
    """Mimic backend session management."""
    if session_id not in sessions:
        sessions[session_id] = AutoSync()
    return sessions[session_id]

# Step 1: User types initial spec
spec_v1 = """result = process_data(raw_input)

x = split dataset into training and test sets

output = transform(x)

print(result, x, output)
"""

print(f"\n{'='*70}")
print("STEP 1: User types spec → Frontend calls /skeleton")
print(f"{'='*70}")
print(f"\nSpec:\n{spec_v1}")

# Simulate /skeleton endpoint
sync = get_or_create_session(SESSION_ID)
new_ir = parse_semiformal(spec_v1)

if sync.sync.ir:
    changes = sync.sync.ir.merge_from_spec_update(new_ir)
    ir = sync.sync.ir
else:
    sync.sync.set_ir(new_ir)
    ir = new_ir

skeleton1 = generate_skeleton(ir)
print(f"\nSkeleton Response:\n{skeleton1}")

# Step 2: User hits Cmd+S → Frontend calls /generate
print(f"\n{'='*70}")
print("STEP 2: User hits Cmd+S → Frontend calls /generate")
print(f"{'='*70}")

generated_code = sync.on_spec_save(spec_v1)
print(f"\nGenerated Code:\n{generated_code.updated_source}")

# Verify nodes have generated code
print(f"\n--- IR State After Generation ---")
for node in ir.nodes.values():
    print(f"{node.name} ({node.node_type.value}): status={node.status.value}, has_code={bool(node.code_text)}")

# Step 3: User continues editing (just typing, not saving yet)
spec_v2 = """result = process_data(raw_input)

x,y = split dataset into training and test sets

output = transform(x)

print(result, x, output)
"""

print(f"\n{'='*70}")
print("STEP 3: User edits spec (x → x,y) → Frontend calls /skeleton")
print(f"{'='*70}")
print(f"\nNew Spec:\n{spec_v2}")

# Simulate /skeleton endpoint AGAIN (using NEW approach)
sync2 = get_or_create_session(SESSION_ID)  # Same session

print(f"\n--- Using NEW systematic approach (merge_and_transform) ---")
# This is what the updated /skeleton endpoint now does
sync2.sync.merge_and_transform(spec_v2)
ir2 = sync2.sync.ir

skeleton2 = generate_skeleton(ir2)
print(f"\nSkeleton Response:\n{skeleton2}")

# Check for issues
print(f"\n{'='*70}")
print("ISSUE DETECTION")
print(f"{'='*70}")

issues_found = []

# Check for duplication
if skeleton2.count("print(result") > 1:
    issues_found.append(f"✗ PRINT DUPLICATION: appears {skeleton2.count('print(result')} times")
    
if skeleton2.count("def process_data") > 1:
    issues_found.append(f"✗ FUNCTION DUPLICATION: process_data defined {skeleton2.count('def process_data')} times")

# Check for indentation issues (statement inside function definition)
lines2 = skeleton2.split('\n')
for i, line in enumerate(lines2):
    if 'def process_data' in line:
        # Check next few lines
        for j in range(i+1, min(i+10, len(lines2))):
            if 'result = process_data' in lines2[j] and not lines2[j].startswith('result'):
                # It's indented!
                issues_found.append(f"✗ INDENTATION BUG: 'result = process_data' appears indented after function def (line {j+1})")

# Check if LHS was transformed
if '(x, y) =' in skeleton2 or 'x, y =' in skeleton2 or 'x,y =' in skeleton2:
    print("✓ LHS transformation applied (x → x,y)")
else:
    issues_found.append("✗ LHS transformation NOT applied")

# Check if generated code preserved
if 'x_train' in skeleton2 or 'train_test_split' in skeleton2:
    print("✓ Generated code preserved")
else:
    issues_found.append("✗ Generated code LOST")

if not issues_found:
    print("\n✅ ALL CHECKS PASSED!")
else:
    print(f"\n❌ ISSUES FOUND:")
    for issue in issues_found:
        print(f"  {issue}")

# Print skeleton line by line for inspection
print(f"\n{'='*70}")
print("FINAL SKELETON LINE-BY-LINE")
print(f"{'='*70}")
for i, line in enumerate(skeleton2.split('\n'), 1):
    print(f"{i:3}: {line}")

print(f"\n{'='*70}")

