"""
Test new node type handlers (function_def, parameter, operator, literal, import)
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from fine_grained_mapper import FineGrainedMapper


def test_new_handlers():
    """Test all new node type handlers"""

    semiformal_code = """def process(x, y):
    return x + y

result = process(10, 5)
print(result)"""

    # Generated Python code (complete, valid)
    generated_code = """def process(x, y):
    return x + y

result = process(10, 5)
print(result)"""

    print("=" * 80)
    print("SEMIFORMAL CODE:")
    print("=" * 80)
    for i, line in enumerate(semiformal_code.split('\n'), 1):
        print(f"{i}: {line}")

    print("\n" + "=" * 80)
    print("GENERATED CODE:")
    print("=" * 80)
    for i, line in enumerate(generated_code.split('\n'), 1):
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
    print("FINE-GRAINED MAPPINGS:")
    print("=" * 80)

    # Track which node types got mapped
    mapped_types = {}
    unmapped_nodes = []

    for node in nodes:
        node_mapped = any(m.node_id == node.id for m in mappings)
        if node_mapped:
            if node.type not in mapped_types:
                mapped_types[node.type] = 0
            mapped_types[node.type] += 1
        else:
            unmapped_nodes.append(node)

    for mapping in mappings:
        intent_node = next((n for n in nodes if n.id == mapping.node_id), None)
        if intent_node:
            print(f"{intent_node.type:15} '{intent_node.content:20}' → "
                  f"line {mapping.line:2} col {mapping.col_start:2}-{mapping.col_end:2} "
                  f"'{mapping.code_text:20}' ({mapping.mapping_type})")

    print("\n" + "=" * 80)
    print("COVERAGE ANALYSIS:")
    print("=" * 80)
    print(f"Total nodes: {len(nodes)}")
    print(f"Mapped nodes: {len(mappings)}")
    print(f"Coverage: {len(mappings)/len(nodes)*100:.1f}%")

    print("\nMapped node types:")
    for node_type, count in sorted(mapped_types.items()):
        print(f"  {node_type}: {count}")

    if unmapped_nodes:
        print(f"\n❌ Unmapped nodes ({len(unmapped_nodes)}):")
        for node in unmapped_nodes:
            print(f"  - {node.type:15} '{node.content}'")
    else:
        print("\n✅ All nodes mapped!")

    # Specific checks for new handlers
    print("\n" + "=" * 80)
    print("HANDLER VERIFICATION:")
    print("=" * 80)

    checks = {
        'function_def': False,
        'parameter': False,
        'operator': False,
        'literal': False,
    }

    for node_type in checks.keys():
        if node_type in mapped_types and mapped_types[node_type] > 0:
            checks[node_type] = True
            print(f"✅ {node_type} handler working ({mapped_types[node_type]} nodes)")
        else:
            print(f"❌ {node_type} handler not working")

    all_passed = all(checks.values())
    if all_passed:
        print("\n✅ All new handlers working correctly!")
    else:
        print("\n❌ Some handlers not working")

    return all_passed and len(unmapped_nodes) == 0


if __name__ == "__main__":
    success = test_new_handlers()
    sys.exit(0 if success else 1)
