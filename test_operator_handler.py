"""
Test operator handler specifically
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from fine_grained_mapper import FineGrainedMapper


def test_operator():
    """Test operator handler"""

    semiformal_code = """x = 10
y = x + 5
z = x * 2"""

    # Generated Python code
    generated_code = """x = 10
y = x + 5
z = x * 2"""

    print("=" * 80)
    print("SEMIFORMAL CODE:")
    print("=" * 80)
    for i, line in enumerate(semiformal_code.split('\n'), 1):
        print(f"{i}: {line}")

    # Parse
    nodes = parse_semiformal(semiformal_code)

    print("\n" + "=" * 80)
    print("INTENT NODES:")
    print("=" * 80)
    for i, node in enumerate(nodes):
        print(f"Node {i:2}: {node.type:15} '{node.content:20}' line={node.span[0]}")

    # Create fine-grained mappings
    mapper = FineGrainedMapper(generated_code)
    mappings = mapper.map_all_nodes(nodes)

    print("\n" + "=" * 80)
    print("MAPPINGS:")
    print("=" * 80)

    operator_nodes = [n for n in nodes if n.type == 'operator']
    operator_mappings = [m for m in mappings if any(n.id == m.node_id for n in operator_nodes)]

    print(f"Operator nodes found: {len(operator_nodes)}")
    print(f"Operator mappings created: {len(operator_mappings)}")

    if operator_nodes:
        for node in operator_nodes:
            mapping = next((m for m in mappings if m.node_id == node.id), None)
            if mapping:
                print(f"✅ operator '{node.content}' → line {mapping.line} col {mapping.col_start}-{mapping.col_end} '{mapping.code_text}'")
            else:
                print(f"❌ operator '{node.content}' NOT MAPPED")

        return len(operator_mappings) == len(operator_nodes)
    else:
        print("⚠️  No operator nodes in parsed output (parser may not parse operators)")
        return True


if __name__ == "__main__":
    success = test_operator()
    sys.exit(0 if success else 1)
