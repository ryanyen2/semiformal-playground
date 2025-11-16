"""
Test import handler
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from fine_grained_mapper import FineGrainedMapper


def test_import():
    """Test import handler"""

    semiformal_code = """import pandas as pd
df = pd.read_csv('data.csv')"""

    # Generated Python code
    generated_code = """import pandas as pd
df = pd.read_csv('data.csv')"""

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

    import_nodes = [n for n in nodes if n.type == 'import']
    import_mappings = [m for m in mappings if any(n.id == m.node_id for n in import_nodes)]

    print(f"Import nodes found: {len(import_nodes)}")
    print(f"Import mappings created: {len(import_mappings)}")

    if import_nodes:
        for node in import_nodes:
            mapping = next((m for m in mappings if m.node_id == node.id), None)
            if mapping:
                print(f"✅ import '{node.content}' → line {mapping.line} col {mapping.col_start}-{mapping.col_end} '{mapping.code_text}'")
            else:
                print(f"❌ import '{node.content}' NOT MAPPED")

        return len(import_mappings) == len(import_nodes)
    else:
        print("⚠️  No import nodes in parsed output")
        return True


if __name__ == "__main__":
    success = test_import()
    sys.exit(0 if success else 1)
