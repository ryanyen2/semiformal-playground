"""
Test with REAL LLM generation using provided API key
"""

import sys
import os
sys.path.insert(0, 'backend')

# Note: Set OPENAI_API_KEY environment variable before running this test
# Example: OPENAI_API_KEY=your-key-here python test_with_real_llm.py
if 'OPENAI_API_KEY' not in os.environ:
    print("Warning: OPENAI_API_KEY not set. LLM features will be disabled.")

from editor import BidirectionalEditor
import json


def test_with_real_llm():
    """Test with actual LLM generation"""

    semiformal_code = """result = load dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)"""

    print("="*80)
    print("SEMIFORMAL CODE:")
    print("="*80)
    for i, line in enumerate(semiformal_code.split('\n'), 1):
        print(f"Line {i}: {line}")

    print("\n" + "="*80)
    print("Initializing editor with LLM...")
    print("="*80)

    editor = BidirectionalEditor()
    state = editor.initialize(semiformal_code)

    print("\n" + "="*80)
    print("GENERATED PYTHON CODE:")
    print("="*80)
    for i, line in enumerate(state['python_code'].split('\n'), 1):
        print(f"{i:2}: {line}")

    print("\n" + "="*80)
    print("INTENT NODES:")
    print("="*80)
    for i, node in enumerate(state['nodes']):
        print(f"Node {i:2}: {node['type']:15} '{node['value'][:30]:30}' line={node['line']}")

    print("\n" + "="*80)
    print("MAPPINGS:")
    print("="*80)
    for i, mapping in enumerate(state['mappings']):
        node_idx = mapping['node_index']
        node = state['nodes'][node_idx]
        gen_line = mapping['code_line']
        snippet = mapping['code_snippet'][:60]

        print(f"Node {node_idx:2} ({node['type']:12} '{node['value'][:15]:15}' sf line {node['line']}) → gen line {gen_line:2}: {snippet}")

    # Check for issues
    print("\n" + "="*80)
    print("ANALYSIS:")
    print("="*80)

    # Group by semiformal line
    semiformal_lines = {
        1: [],  # result = load dataset and process it
        3: [],  # output = transform(result)
        5: [],  # x, y = {split...}
        7: [],  # print(output)
    }

    for mapping in state['mappings']:
        node_idx = mapping['node_index']
        node = state['nodes'][node_idx]
        sf_line = node['line']
        if sf_line in semiformal_lines:
            semiformal_lines[sf_line].append((node, mapping))

    # Check each semiformal line
    for sf_line, items in sorted(semiformal_lines.items()):
        if not items:
            print(f"\n❌ Semiformal line {sf_line}: NO MAPPINGS!")
            continue

        print(f"\nSemiformal line {sf_line}:")
        gen_lines = set()
        for node, mapping in items:
            gen_line = mapping['code_line']
            snippet = mapping['code_snippet'][:50]
            gen_lines.add(gen_line)
            print(f"  {node['type']:12} '{node['value'][:20]:20}' → line {gen_line:2}: {snippet}")

        # Check if all nodes from this line map to the same area
        if len(gen_lines) > 3:
            print(f"  ⚠️  Warning: Nodes map to {len(gen_lines)} different lines (might be spread out)")

    # Check for unmapped nodes
    mapped_indices = {m['node_index'] for m in state['mappings']}
    unmapped = []
    for i, node in enumerate(state['nodes']):
        if i not in mapped_indices:
            unmapped.append((i, node))

    if unmapped:
        print(f"\n❌ {len(unmapped)} nodes NOT MAPPED:")
        for i, node in unmapped:
            print(f"  Node {i:2}: {node['type']:12} '{node['value'][:30]}'")

    # Check for duplicate code
    print("\n" + "="*80)
    print("CHECKING FOR DUPLICATE CODE:")
    print("="*80)
    code_lines = state['python_code'].split('\n')
    line_counts = {}
    for i, line in enumerate(code_lines, 1):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            if stripped not in line_counts:
                line_counts[stripped] = []
            line_counts[stripped].append(i)

    duplicates = {line: lines for line, lines in line_counts.items() if len(lines) > 1}
    if duplicates:
        print(f"\n⚠️  Found {len(duplicates)} duplicated lines:")
        for line_text, line_nums in list(duplicates.items())[:5]:
            print(f"  '{line_text[:60]}' appears at lines: {line_nums}")
    else:
        print("\n✓ No duplicate code found")

    return state


if __name__ == "__main__":
    state = test_with_real_llm()
