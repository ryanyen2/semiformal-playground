"""
Test suite for robust bidirectional mapping algorithm.

Tests various edit scenarios across DIRECT, HYBRID, and NL node categories.
"""

import sys
sys.path.insert(0, 'backend')

from backend.ast_parser import parse_semiformal
from backend.robust_mapper import RobustMapper
from backend.node_classifier import NodeClassifier
from backend.skeleton_generator import generate_skeleton
from backend.mapping_types import MappingCategory, EditType
from backend.robust_sync import RobustIRSync


def test_lhs_change():
    """Test LHS structural change (x → x,y) with code preservation."""
    print("\n=== Test 1: LHS Change (x → x,y) ===")

    # Initial spec with NL
    spec_v1 = """result = process_data(raw_input)
x = split dataset into training and test sets
output = transform(x)
print(result, x, output)"""

    # Parse and generate initial code
    ir_v1 = parse_semiformal(spec_v1)
    skeleton_v1 = generate_skeleton(ir_v1)

    print(f"Initial skeleton:\n{skeleton_v1}\n")

    # Manually simulate LLM generation for x
    for node in ir_v1.nodes.values():
        if node.name == 'x':
            node.code_text = "x = (train_data, test_data)"
            node.status = node.status.__class__.GENERATED

    skeleton_v1_generated = generate_skeleton(ir_v1)
    print(f"After LLM generation:\n{skeleton_v1_generated}\n")

    # Build mapping
    mapper = RobustMapper()
    mapping_v1 = mapper.build_mapping(ir_v1, skeleton_v1_generated)

    # Classify nodes
    classifier = NodeClassifier(ir_v1)
    categories = classifier.classify_all()

    print("Node classifications:")
    for node_id, category in categories.items():
        node = ir_v1.nodes[node_id]
        print(f"  {node.name}: {category.value}")

    # Edit: Change x to x,y
    spec_v2 = """result = process_data(raw_input)
x, y = split dataset into training and test sets
output = transform(x)
print(result, x, output)"""

    # Use robust sync to handle the change
    robust_sync = RobustIRSync(use_llm=False)  # Don't use LLM for testing
    robust_sync.set_ir(ir_v1)
    robust_sync.mapping = mapping_v1

    # Merge and transform
    ir_v2, mapping_v2 = robust_sync.merge_and_transform_robust(
        spec_v2,
        skeleton_v1_generated
    )

    # Generate new skeleton
    skeleton_v2 = generate_skeleton(ir_v2)

    print(f"After LHS change:\n{skeleton_v2}\n")

    # Verify
    if "(x, y) =" in skeleton_v2 and "train_data, test_data" in skeleton_v2:
        print("✓ LHS transformation successful - code preserved!")
        return True
    else:
        print("✗ LHS transformation failed")
        return False


def test_function_call_signature_change():
    """Test function call signature change (HYBRID node)."""
    print("\n=== Test 2: Function Call Signature Change ===")

    spec_v1 = """result = process_data(raw_input)
print(result)"""

    ir_v1 = parse_semiformal(spec_v1)
    skeleton_v1 = generate_skeleton(ir_v1)

    print(f"Initial skeleton:\n{skeleton_v1}\n")

    # Classify
    classifier = NodeClassifier(ir_v1)
    categories = classifier.classify_all()

    print("Classifications:")
    for node_id, category in categories.items():
        node = ir_v1.nodes[node_id]
        print(f"  {node.name}: {category.value}")

    # Expected: process_data is HYBRID (call is direct, definition needs gen)
    process_data_node = None
    for node in ir_v1.nodes.values():
        if node.name == 'process_data':
            process_data_node = node
            break

    if process_data_node:
        category = categories[process_data_node.id]
        if category == MappingCategory.HYBRID:
            print("✓ process_data correctly classified as HYBRID")
            return True
        else:
            print(f"✗ process_data incorrectly classified as {category.value}")
            return False
    else:
        print("✗ process_data node not found")
        return False


def test_nl_content_change():
    """Test natural language content change (regeneration required)."""
    print("\n=== Test 3: NL Content Change ===")

    spec_v1 = "x = load dataset and preprocess"

    ir_v1 = parse_semiformal(spec_v1)
    skeleton_v1 = generate_skeleton(ir_v1)

    print(f"Initial skeleton:\n{skeleton_v1}\n")

    # Classify
    classifier = NodeClassifier(ir_v1)
    categories = classifier.classify_all()

    print("Classifications:")
    for node_id, category in categories.items():
        node = ir_v1.nodes[node_id]
        print(f"  {node.name}: {category.value} - {node.node_type.value}")

    # Expected: x is NL
    x_node = None
    for node in ir_v1.nodes.values():
        if node.name == 'x':
            x_node = node
            break

    if x_node:
        category = categories[x_node.id]
        if category == MappingCategory.NL:
            print("✓ NL expression correctly classified")
            return True
        else:
            print(f"✗ NL expression incorrectly classified as {category.value}")
            return False
    else:
        print("✗ x node not found")
        return False


def test_direct_value_change():
    """Test direct value change (no regeneration needed)."""
    print("\n=== Test 4: Direct Value Change ===")

    spec = """x = 5
y = 10
print(x + y)"""

    ir = parse_semiformal(spec)
    skeleton = generate_skeleton(ir)

    print(f"Skeleton:\n{skeleton}\n")

    # Classify
    classifier = NodeClassifier(ir)
    categories = classifier.classify_all()

    print("Classifications:")
    for node_id, category in categories.items():
        node = ir.nodes[node_id]
        print(f"  {node.name}: {category.value}")

    # Expected: x and y are DIRECT (concrete values)
    direct_count = sum(1 for c in categories.values() if c == MappingCategory.DIRECT)

    if direct_count >= 2:  # x and y should be direct
        print(f"✓ Found {direct_count} DIRECT nodes")
        return True
    else:
        print(f"✗ Only found {direct_count} DIRECT nodes, expected at least 2")
        return False


def test_mapping_consistency():
    """Test bidirectional mapping consistency."""
    print("\n=== Test 5: Mapping Consistency ===")

    spec = """def process_data(input):
    ...

result = process_data(raw_input)
x = split data
print(result, x)"""

    ir = parse_semiformal(spec)
    skeleton = generate_skeleton(ir)

    print(f"Skeleton:\n{skeleton}\n")

    # Build mapping
    mapper = RobustMapper()
    mapping = mapper.build_mapping(ir, skeleton)

    # Check forward → reverse consistency
    errors = []
    for node_id, ast_paths in mapping.forward.ir_to_ast.items():
        for ast_path in ast_paths:
            reverse_id = mapping.reverse.get_node_id(ast_path)
            if reverse_id != node_id:
                errors.append(f"Inconsistency: {node_id} → {ast_path} → {reverse_id}")

    if not errors:
        print("✓ Mapping is bidirectionally consistent")
        print(f"  Mapped {len(mapping.forward.ir_to_ast)} nodes")
        print(f"  Found {len(mapping.underspec_nodes)} underspecified nodes")
        return True
    else:
        print("✗ Mapping inconsistencies found:")
        for error in errors:
            print(f"  {error}")
        return False


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 70)
    print("ROBUST BIDIRECTIONAL MAPPING TEST SUITE")
    print("=" * 70)

    tests = [
        ("LHS Change", test_lhs_change),
        ("Function Call Signature", test_function_call_signature_change),
        ("NL Content Change", test_nl_content_change),
        ("Direct Value Change", test_direct_value_change),
        ("Mapping Consistency", test_mapping_consistency),
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n✗ Test '{name}' failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed_count}/{total_count} tests passed")

    return passed_count == total_count


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
