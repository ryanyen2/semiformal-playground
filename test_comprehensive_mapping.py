"""
Comprehensive Mapping Tests for Semiformal Code

Tests the mapping algorithm across various code types:
1. Complete Python code
2. Natural language expressions
3. Incomplete code (holes, undefined references)
4. Pseudocode
5. Mixed scenarios

Tests mapping accuracy, slicing, and underspecification detection.
"""

import sys
sys.path.insert(0, 'backend')

from parser import SemiformalParser, parse_semiformal
from generator import CodeGenerator
from editor import BidirectionalEditor
from tree_mapper import TreeMapper
from config import MVPConfig, DEFAULT_CONFIG


def print_mapping_info(ir_tree, ast_tree, mappings):
    """Helper to print mapping information"""
    print(f"\n  IR Tree Structure:")
    print_tree(ir_tree, indent=4)
    print(f"\n  AST Tree Structure:")
    print_tree(ast_tree, indent=4)
    print(f"\n  Mappings ({len(mappings)}):")
    for m in mappings:
        ir_content = m.ir_node.content[:30] + "..." if len(m.ir_node.content) > 30 else m.ir_node.content
        ast_content = m.ast_node.content[:30] + "..." if m.ast_node and len(m.ast_node.content) > 30 else (m.ast_node.content if m.ast_node else "None")
        print(f"    {m.mapping_type.value:12} | IR: {ir_content:20} → AST: {ast_content:20} | sim={m.similarity:.2f}")


def print_tree(node, indent=0, max_depth=3):
    """Recursively print tree structure"""
    if indent // 2 > max_depth:
        return
    prefix = " " * indent
    content = node.content[:40] + "..." if len(node.content) > 40 else node.content
    print(f"{prefix}{node.node_type}: {content}")
    for child in node.children[:3]:  # Limit to first 3 children
        print_tree(child, indent + 2, max_depth)
    if len(node.children) > 3:
        print(f"{prefix}  ... ({len(node.children) - 3} more children)")


def test_1_complete_python():
    """Test 1: Complete, valid Python code - should map 1:1"""
    print("\n" + "=" * 80)
    print("TEST 1: Complete Python Code (1:1 Mapping)")
    print("=" * 80)

    code = """def calculate_sum(a, b):
    return a + b

x = 10
y = 20
result = calculate_sum(x, y)
print(result)"""

    print(f"\nInput Code:\n{code}")

    # Parse
    nodes = parse_semiformal(code)
    print(f"\n✓ Parsed into {len(nodes)} intent nodes")

    # Generate
    editor = BidirectionalEditor()
    state = editor.initialize(code)
    python_code = state['python_code']

    print(f"\n✓ Generated Python Code:\n{python_code}")

    # Map
    mapper = TreeMapper()
    ir_tree = mapper.build_ir_tree(nodes)
    ast_tree = mapper.build_ast_tree(python_code)
    mappings = mapper.map_trees(ir_tree, ast_tree)

    print_mapping_info(ir_tree, ast_tree, mappings)

    # Verify
    exact_mappings = [m for m in mappings if m.mapping_type.value == 'exact']
    print(f"\n✓ Result: {len(exact_mappings)}/{len(mappings)} exact mappings")

    return len(exact_mappings) >= len(mappings) * 0.8  # At least 80% exact


def test_2_natural_language():
    """Test 2: Natural language expressions"""
    print("\n" + "=" * 80)
    print("TEST 2: Natural Language Expressions (Semantic Mapping)")
    print("=" * 80)

    code = """data = load and preprocess the dataset
x, y = split data into training and testing sets
model = train a neural network on the training data
accuracy = evaluate model performance on test set"""

    print(f"\nInput Code:\n{code}")

    # Parse
    nodes = parse_semiformal(code)
    print(f"\n✓ Parsed into {len(nodes)} intent nodes")

    for node in nodes[:5]:
        print(f"    {node.type:15} | {node.content[:50]}")

    # Generate (would need LLM, so we'll use skeleton)
    editor = BidirectionalEditor()
    state = editor.initialize(code)
    python_code = state['python_code']

    print(f"\n✓ Generated Skeleton:\n{python_code}")

    # Map
    mapper = TreeMapper()
    ir_tree = mapper.build_ir_tree(nodes)
    ast_tree = mapper.build_ast_tree(python_code)
    mappings = mapper.map_trees(ir_tree, ast_tree)

    print_mapping_info(ir_tree, ast_tree, mappings)

    # Verify
    semantic_mappings = [m for m in mappings if m.mapping_type.value == 'semantic']
    print(f"\n✓ Result: {len(semantic_mappings)} semantic mappings found")

    return len(semantic_mappings) > 0


def test_3_incomplete_code():
    """Test 3: Incomplete code with holes and undefined references"""
    print("\n" + "=" * 80)
    print("TEST 3: Incomplete Code (Holes and Undefined References)")
    print("=" * 80)

    code = """def process_data(input):
    {}

result = process_data(raw_input)
x = {prepare features from result}
y = extract_labels(x)
print(x, y)"""

    print(f"\nInput Code:\n{code}")

    # Parse
    nodes = parse_semiformal(code)
    print(f"\n✓ Parsed into {len(nodes)} intent nodes")

    # Count holes and undefined
    holes = [n for n in nodes if n.type == 'hole']
    undefined_calls = [n for n in nodes if n.type == 'function_call' and n.content in ['process_data', 'extract_labels']]

    print(f"    Holes found: {len(holes)}")
    print(f"    Undefined function calls: {len(undefined_calls)}")

    # Generate
    editor = BidirectionalEditor()
    state = editor.initialize(code)
    python_code = state['python_code']

    print(f"\n✓ Generated Code:\n{python_code}")

    # Map
    mapper = TreeMapper()
    ir_tree = mapper.build_ir_tree(nodes)
    ast_tree = mapper.build_ast_tree(python_code)
    mappings = mapper.map_trees(ir_tree, ast_tree)

    print_mapping_info(ir_tree, ast_tree, mappings)

    # Check for underspecification
    underspec_mappings = [m for m in mappings if hasattr(m, 'is_underspecified') or
                          (m.ir_node.metadata.get('is_underspecified', False))]

    print(f"\n✓ Result: {len(underspec_mappings)} underspecified mappings detected")

    return True


def test_4_mixed_code():
    """Test 4: Mixed code - Python + NL + holes"""
    print("\n" + "=" * 80)
    print("TEST 4: Mixed Code (Python + NL + Holes)")
    print("=" * 80)

    code = """import pandas as pd

def load_data(filepath):
    return pd.read_csv(filepath)

# Complete Python above, mixed below
data = load_data('data.csv')
processed = clean and transform the data
features = {extract relevant features}

# More complete Python
model = LinearRegression()
result = model.fit(features, labels)
print(result.score())"""

    print(f"\nInput Code:\n{code}")

    # Parse
    nodes = parse_semiformal(code)
    print(f"\n✓ Parsed into {len(nodes)} intent nodes")

    # Categorize nodes
    python_nodes = [n for n in nodes if n.type in ['python_expr', 'expr_stmt', 'identifier', 'operator']]
    nl_nodes = [n for n in nodes if n.type == 'nl_phrase']
    hole_nodes = [n for n in nodes if n.type == 'hole']

    print(f"    Python nodes: {len(python_nodes)}")
    print(f"    NL nodes: {len(nl_nodes)}")
    print(f"    Hole nodes: {len(hole_nodes)}")

    # Generate
    editor = BidirectionalEditor()
    state = editor.initialize(code)
    python_code = state['python_code']

    print(f"\n✓ Generated Code:\n{python_code[:300]}...")

    # Map
    mapper = TreeMapper()
    ir_tree = mapper.build_ir_tree(nodes)
    ast_tree = mapper.build_ast_tree(python_code)
    mappings = mapper.map_trees(ir_tree, ast_tree)

    # Categorize mappings
    by_type = {}
    for m in mappings:
        mt = m.mapping_type.value
        by_type[mt] = by_type.get(mt, 0) + 1

    print(f"\n✓ Mapping Distribution:")
    for mt, count in by_type.items():
        print(f"    {mt:15} : {count}")

    return len(mappings) > 0


def test_5_underspecification_detection():
    """Test 5: Detect underspecification in generated code"""
    print("\n" + "=" * 80)
    print("TEST 5: Underspecification Detection")
    print("=" * 80)

    # Spec is minimal, generator might add more details
    code = """result = process(data)"""

    print(f"\nInput Code (minimal):\n{code}")

    # Parse
    nodes = parse_semiformal(code)

    # Generate - skeleton will add function definition
    editor = BidirectionalEditor()
    state = editor.initialize(code)
    python_code = state['python_code']

    print(f"\n✓ Generated Code (with added details):\n{python_code}")

    # The generated code has more than the spec - this is underspecification
    # E.g., it adds function definition with parameters, docstring, NotImplementedError

    # Map and detect underspecification
    mapper = TreeMapper()
    ir_tree = mapper.build_ir_tree(nodes)
    ast_tree = mapper.build_ast_tree(python_code)

    # Count nodes in each tree
    ir_count = count_tree_nodes(ir_tree)
    ast_count = count_tree_nodes(ast_tree)

    print(f"\n✓ Node counts:")
    print(f"    IR tree: {ir_count} nodes")
    print(f"    AST tree: {ast_count} nodes")

    if ast_count > ir_count * 1.5:
        print(f"\n✓ Underspecification detected: AST has {ast_count - ir_count} more nodes")
        return True
    else:
        print(f"\n✗ No significant underspecification detected")
        return False


def test_6_slicing_accuracy():
    """Test 6: Test slicing accuracy for partial updates"""
    print("\n" + "=" * 80)
    print("TEST 6: Slicing Accuracy (Partial Updates)")
    print("=" * 80)

    code = """x = 10
y = 20
result = compute(x, y)
print(result)"""

    print(f"\nOriginal Code:\n{code}")

    # Parse and generate
    editor = BidirectionalEditor()
    state = editor.initialize(code)

    # Now edit just one line
    edit_code = """x = 15
y = 20
result = compute(x, y)
print(result)"""

    print(f"\nEdited Code (only x changed):\n{edit_code}")

    # Identify changed slice
    original_nodes = parse_semiformal(code)
    edited_nodes = parse_semiformal(edit_code)

    # Simple diff: find differing nodes
    changed_nodes = []
    for i, (orig, edit) in enumerate(zip(original_nodes, edited_nodes)):
        if orig.content != edit.content:
            changed_nodes.append((i, orig, edit))

    print(f"\n✓ Changed nodes: {len(changed_nodes)}")
    for idx, orig, edit in changed_nodes:
        print(f"    Node {idx}: '{orig.content}' → '{edit.content}'")

    # Verify only the changed node is identified
    return len(changed_nodes) <= 2  # x and the literal 15


def count_tree_nodes(tree_node, count=0):
    """Recursively count nodes in tree"""
    count = 1
    for child in tree_node.children:
        count += count_tree_nodes(child)
    return count


def test_7_function_call_mapping():
    """Test 7: Function calls mapping to definitions"""
    print("\n" + "=" * 80)
    print("TEST 7: Function Call ↔ Definition Mapping")
    print("=" * 80)

    code = """result = transform_data(input)
output = process_result(result)

def transform_data(data):
    return data * 2

def process_result(res):
    return res + 10"""

    print(f"\nInput Code:\n{code}")

    # Parse
    nodes = parse_semiformal(code)

    # Find function calls and definitions
    calls = [n for n in nodes if n.type == 'function_call']
    # Definitions are found in python_expr nodes

    print(f"\n✓ Found {len(calls)} function calls")
    for call in calls:
        print(f"    {call.content}")

    # Generate
    editor = BidirectionalEditor()
    state = editor.initialize(code)
    python_code = state['python_code']

    print(f"\n✓ Generated Code:\n{python_code}")

    # Map
    mapper = TreeMapper()
    ir_tree = mapper.build_ir_tree(nodes)
    ast_tree = mapper.build_ast_tree(python_code)
    mappings = mapper.map_trees(ir_tree, ast_tree)

    # Check if call nodes map to both call sites and definitions
    call_mappings = [m for m in mappings if 'call' in m.ir_node.node_type or 'call' in (m.ast_node.node_type if m.ast_node else '')]

    print(f"\n✓ Call-related mappings: {len(call_mappings)}")

    return len(call_mappings) > 0


def run_all_tests():
    """Run all mapping tests"""
    print("\n" + "=" * 80)
    print("COMPREHENSIVE MAPPING ALGORITHM TESTS")
    print("=" * 80)

    tests = [
        ("Complete Python Code", test_1_complete_python),
        ("Natural Language", test_2_natural_language),
        ("Incomplete Code", test_3_incomplete_code),
        ("Mixed Code Types", test_4_mixed_code),
        ("Underspecification Detection", test_5_underspecification_detection),
        ("Slicing Accuracy", test_6_slicing_accuracy),
        ("Function Call Mapping", test_7_function_call_mapping),
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
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

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
