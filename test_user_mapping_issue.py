"""
Debug mapping issue with user's example
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from fine_grained_mapper import FineGrainedMapper
import json


def test_mapping(semiformal_code, generated_code):
    """Test mapping and show detailed output"""
    
    print("=" * 80)
    print("SEMIFORMAL CODE:")
    print("=" * 80)
    for i, line in enumerate(semiformal_code.split('\n'), 0):
        print(f"SF line {i}: {line}")
    
    print("\n" + "=" * 80)
    print("GENERATED CODE:")
    print("=" * 80)
    for i, line in enumerate(generated_code.split('\n'), 1):
        print(f"Code line {i}: {line}")
    
    # Parse
    nodes = parse_semiformal(semiformal_code)
    
    print("\n" + "=" * 80)
    print("PARSED INTENT NODES:")
    print("=" * 80)
    for i, node in enumerate(nodes):
        is_def = node.metadata.get('is_definition', False)
        role = ' (DEF)' if is_def else ' (REF)' if node.type == 'identifier' else ''
        print(f"Node {i:2}: {node.type:15} '{node.content:25}' SF_line={node.span[0]}{role}")
    
    # Map
    mapper = FineGrainedMapper(generated_code)
    mappings = mapper.map_all_nodes(nodes)
    
    print("\n" + "=" * 80)
    print("MAPPINGS (Node → Code):")
    print("=" * 80)
    
    for i, node in enumerate(nodes):
        mapping = next((m for m in mappings if m.node_id == node.id), None)
        if mapping:
            is_def = node.metadata.get('is_definition', False)
            role = ' (DEF)' if is_def else ' (REF)' if node.type == 'identifier' else ''
            print(f"Node {i:2}: {node.type:15} '{node.content:20}'{role}")
            print(f"         SF_line={node.span[0]} → Code_line={mapping.line} col {mapping.col_start}-{mapping.col_end}")
            print(f"         Mapped to: '{mapping.code_text}' ({mapping.mapping_type}, conf={mapping.confidence:.2f})")
        else:
            print(f"Node {i:2}: {node.type:15} '{node.content:20}' → NOT MAPPED ❌")
        print()
    
    # Group by type to see patterns
    print("\n" + "=" * 80)
    print("MAPPING ANALYSIS BY TYPE:")
    print("=" * 80)
    
    by_type = {}
    for node in nodes:
        if node.type not in by_type:
            by_type[node.type] = []
        mapping = next((m for m in mappings if m.node_id == node.id), None)
        by_type[node.type].append((node, mapping))
    
    for node_type, items in sorted(by_type.items()):
        print(f"\n{node_type}:")
        for node, mapping in items:
            if mapping:
                print(f"  '{node.content}' (SF:{node.span[0]}) → Code:{mapping.line} '{mapping.code_text}'")
            else:
                print(f"  '{node.content}' (SF:{node.span[0]}) → NOT MAPPED")


# Test with a simple example first
print("TEST 1: Simple variable references")
print("=" * 80)

semiformal1 = """x = 10
y = x + 5
z = x * 2
print(x, y, z)"""

generated1 = """x = 10
y = x + 5
z = x * 2
print(x, y, z)"""

test_mapping(semiformal1, generated1)

print("\n\n" + "=" * 100)
print("If you have a different example that's failing, provide it and I'll test it")
print("=" * 100)

