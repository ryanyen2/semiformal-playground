"""
Verify that the reference mapping fix (distance * 20) works correctly.

This tests Issue #3 from CORE_ISSUES_ANALYSIS.md:
Multiple references to same variable should map to their actual locations,
not all to the first occurrence.
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from fine_grained_mapper import FineGrainedMapper


def test_reference_fix():
    """Test that multiple x references map to correct locations"""

    semiformal_code = """x = 10
y = x + 5
z = x * 2
print(x, y, z)"""

    generated_code = """x = 10
y = x + 5
z = x * 2
print(x, y, z)"""

    print("=" * 80)
    print("TESTING: Multiple references to same variable")
    print("=" * 80)
    print("\nGenerated code:")
    for i, line in enumerate(generated_code.split('\n'), 1):
        print(f"  {i}: {line}")

    # Parse
    nodes = parse_semiformal(semiformal_code)

    # Find all x identifier nodes
    x_nodes = [(i, n) for i, n in enumerate(nodes) if n.type == 'identifier' and n.content == 'x']

    print(f"\nFound {len(x_nodes)} identifier nodes for 'x':")
    for i, node in x_nodes:
        is_def = node.metadata.get('is_definition', False)
        role = 'definition' if is_def else 'reference'
        print(f"  Node {i}: x ({role}) on semiformal line {node.span[0]}")

    # Map
    mapper = FineGrainedMapper(generated_code)
    mappings = mapper.map_all_nodes(nodes)

    print("\n" + "=" * 80)
    print("MAPPINGS:")
    print("=" * 80)

    success = True

    # Expected line for each x node based on semiformal line
    # Node 0: x definition (semiformal line 0) → should map to code line 1
    # Node 3: x reference (semiformal line 1) → should map to code line 2
    # Node 7: x reference (semiformal line 2) → should map to code line 3
    # Node 10: x reference (semiformal line 3) → should map to code line 4

    for idx, node in x_nodes:
        mapping = next((m for m in mappings if m.node_id == node.id), None)
        if mapping:
            # Expected: semiformal line N should map to code line N+1
            # (since semiformal is 0-indexed, code is 1-indexed)
            expected_line = node.span[0] + 1
            actual_line = mapping.line
            is_def = node.metadata.get('is_definition', False)
            actual_role = 'definition' if is_def else 'reference'

            status = "✅" if actual_line == expected_line else "❌"
            print(f"{status} Node {idx}: x ({actual_role}) on SF line {node.span[0]} → code line {actual_line} col {mapping.col_start}-{mapping.col_end}")

            if actual_line != expected_line:
                print(f"   ERROR: Expected code line {expected_line}, got {actual_line}")
                success = False
        else:
            print(f"❌ Node {idx}: x NOT MAPPED")
            success = False

    print("\n" + "=" * 80)
    print("RESULT:")
    print("=" * 80)

    if success:
        print("✅ All x references map to correct locations!")
        print("✅ Issue #3 (Duplicate Reference Mapping) FIXED")
    else:
        print("❌ Some x references map to wrong locations")
        print("❌ Issue #3 still present")

    return success


if __name__ == "__main__":
    success = test_reference_fix()
    sys.exit(0 if success else 1)
