"""
Test with REAL example to debug mapping issues
"""

import sys
sys.path.insert(0, 'backend')

from editor import BidirectionalEditor
import json


def test_real_example():
    """Test with the user's actual example"""

    semiformal_code = """result = load dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)"""

    print("="*80)
    print("SEMIFORMAL CODE:")
    print("="*80)
    for i, line in enumerate(semiformal_code.split('\n'), 1):
        print(f"Line {i}: {line}")

    editor = BidirectionalEditor()
    state = editor.initialize(semiformal_code)

    print("\n" + "="*80)
    print("GENERATED PYTHON CODE:")
    print("="*80)
    for i, line in enumerate(state['python_code'].split('\n'), 1):
        print(f"Line {i:2}: {line}")

    print("\n" + "="*80)
    print("PARSED NODES:")
    print("="*80)
    for i, node in enumerate(state['nodes']):
        print(f"Node {i}: type={node['type']}, value={node['value']!r}, semiformal_line={node['line']}")

    print("\n" + "="*80)
    print("MAPPINGS (Node → Generated Code):")
    print("="*80)

    # Get actual mappings with details
    for i, mapping in enumerate(state['mappings']):
        node_idx = mapping['node_index']
        node = state['nodes'][node_idx]
        code_line = mapping['code_line']
        snippet = mapping['code_snippet']

        print(f"\nMapping {i}:")
        print(f"  Node {node_idx}: {node['type']}={node['value']!r} (semiformal line {node['line']})")
        print(f"  → Generated line {code_line}: {snippet!r}")

        # Check if mapping makes sense
        semiformal_line = node['line']
        if abs(code_line - semiformal_line) > 10:
            print(f"  ⚠️  WARNING: Semiformal line {semiformal_line} maps to generated line {code_line} (offset: {code_line - semiformal_line})")

    print("\n" + "="*80)
    print("ANALYSIS:")
    print("="*80)

    # Analyze each semiformal line
    semiformal_lines = semiformal_code.split('\n')
    for sf_line_num, sf_line in enumerate(semiformal_lines, 1):
        if not sf_line.strip():
            continue

        print(f"\nSemiformal line {sf_line_num}: {sf_line!r}")

        # Find nodes from this line
        nodes_on_line = [n for n in state['nodes'] if n['line'] == sf_line_num]
        print(f"  Nodes: {len(nodes_on_line)}")
        for node in nodes_on_line:
            print(f"    - {node['type']}={node['value']!r}")

        # Find mappings for these nodes
        node_indices = [i for i, n in enumerate(state['nodes']) if n['line'] == sf_line_num]
        mappings_for_line = [m for m in state['mappings'] if m['node_index'] in node_indices]

        print(f"  Mapped to generated lines:")
        mapped_lines = set()
        for m in mappings_for_line:
            mapped_lines.add(m['code_line'])
            print(f"    - Line {m['code_line']}: {m['code_snippet']!r}")

        # Check if mapping makes sense
        if mapped_lines:
            avg_mapped = sum(mapped_lines) / len(mapped_lines)
            if abs(avg_mapped - sf_line_num) > 10:
                print(f"  ❌ PROBLEM: Expected to map near line {sf_line_num}, but maps to ~line {int(avg_mapped)}")
        else:
            print(f"  ❌ PROBLEM: No mappings found!")

    print("\n" + "="*80)
    print("EXPECTED vs ACTUAL:")
    print("="*80)
    print("\nExpectations:")
    print("1. Semiformal line 1 'result = load dataset...' should map to code loading/processing data")
    print("2. Semiformal line 3 'output = transform(result)' should map to transform call")
    print("3. Semiformal line 5 'x, y = {split...}' should map to train_test_split call")
    print("4. Semiformal line 7 'print(output)' should map to print(output)")

    print("\n" + "="*80)
    print("CHECKING COMPLETENESS CLASSIFIER:")
    print("="*80)

    if editor.translator and editor.translator.classifier:
        print("✓ Classifier available")

        # Check each node's completeness
        for i, node in enumerate(editor.intent_nodes):
            completeness = editor.translator.classifier.classify(node)
            print(f"Node {i} ({node.type}={node.content!r}): {completeness.value}")
    else:
        print("❌ Classifier NOT available")

    # Return for further inspection
    return {
        'semiformal': semiformal_code,
        'python': state['python_code'],
        'nodes': editor.intent_nodes,
        'mappings': editor.mappings,
        'state': state
    }


if __name__ == "__main__":
    result = test_real_example()

    print("\n" + "="*80)
    print("DONE - Review the output above to see mapping issues")
    print("="*80)
