"""
Test Edit Detection and Strategy Selection

Tests that the system correctly identifies when to use:
- Direct AST edits (for complete Python)
- Hybrid approach (for incomplete Python)
- LLM regeneration (for natural language)
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from completeness_classifier import (
    CompletenessClassifier,
    NodeCompleteness,
    classify_edit_scenario
)


def test_1_direct_edit_print_add_arg():
    """
    TEST: print(output) → print(output, x)
    EXPECTED: Direct AST edit (NO LLM)
    REASON: Both are complete Python with defined identifiers
    """
    print("\n" + "="*80)
    print("TEST 1: Add argument to print() - Should be DIRECT edit")
    print("="*80)

    old_code = "print(output)"
    new_code = "print(output, x)"

    print(f"Old: {old_code}")
    print(f"New: {new_code}")

    # Parse both
    old_nodes = parse_semiformal(old_code)
    new_nodes = parse_semiformal(new_code)

    # Classify
    result = classify_edit_scenario(old_code, new_code, old_nodes, new_nodes)

    print(f"\nStrategy: {result['strategy']}")
    print(f"Reason: {result['reason']}")
    print(f"Affected lines: {result['affected_lines']}")

    # Verify
    if result['strategy'] == 'direct':
        print("\n✅ PASS: Correctly identified as direct edit")
        return True
    else:
        print(f"\n❌ FAIL: Expected 'direct', got '{result['strategy']}'")
        return False


def test_2_incomplete_function_call():
    """
    TEST: result = process_data(input)  [no definition]
    EXPECTED: Hybrid (direct on call, LLM on definition)
    REASON: Function call exists but function not defined
    """
    print("\n" + "="*80)
    print("TEST 2: Function call without definition - Should be HYBRID")
    print("="*80)

    code = "result = process_data(input)"

    print(f"Code: {code}")

    nodes = parse_semiformal(code)
    classifier = CompletenessClassifier(nodes)

    # Find function call node
    call_nodes = [n for n in nodes if n.type == 'function_call']

    if call_nodes:
        call_node = call_nodes[0]
        completeness = classifier.classify(call_node)

        print(f"\nFunction call '{call_node.content}' classified as: {completeness.value}")

        if completeness == NodeCompleteness.INCOMPLETE:
            print("\n✅ PASS: Correctly identified as incomplete")
            return True
        else:
            print(f"\n❌ FAIL: Expected INCOMPLETE, got {completeness.value}")
            return False
    else:
        print("\n❌ FAIL: No function call found")
        return False


def test_3_natural_language():
    """
    TEST: data = load and preprocess dataset
    EXPECTED: NL classification → LLM regeneration
    REASON: Contains natural language phrases
    """
    print("\n" + "="*80)
    print("TEST 3: Natural language expression - Should be NL")
    print("="*80)

    code = "data = load and preprocess dataset"

    print(f"Code: {code}")

    nodes = parse_semiformal(code)
    classifier = CompletenessClassifier(nodes)

    # Classify line
    completeness = classifier.classify_line(0)

    print(f"\nLine classified as: {completeness.value}")

    if completeness == NodeCompleteness.NL:
        print("\n✅ PASS: Correctly identified as natural language")
        return True
    else:
        print(f"\n❌ FAIL: Expected NL, got {completeness.value}")
        return False


def test_4_complete_python():
    """
    TEST: x = 10; y = 20; print(x + y)
    EXPECTED: All COMPLETE
    REASON: All valid Python with defined identifiers
    """
    print("\n" + "="*80)
    print("TEST 4: Complete Python code - Should be COMPLETE")
    print("="*80)

    code = """x = 10
y = 20
print(x + y)"""

    print(f"Code:\n{code}")

    nodes = parse_semiformal(code)
    classifier = CompletenessClassifier(nodes)

    # Classify each line
    results = {}
    for line_num in range(3):
        completeness = classifier.classify_line(line_num)
        results[line_num] = completeness
        print(f"Line {line_num}: {completeness.value}")

    # All should be complete
    all_complete = all(c == NodeCompleteness.COMPLETE for c in results.values())

    if all_complete:
        print("\n✅ PASS: All lines correctly identified as complete")
        return True
    else:
        print(f"\n❌ FAIL: Not all lines identified as complete")
        return False


def test_5_edit_with_definition():
    """
    TEST: Add argument to defined function call
    EXPECTED: DIRECT edit
    REASON: Function is defined, so call is complete Python
    """
    print("\n" + "="*80)
    print("TEST 5: Edit call to defined function - Should be DIRECT")
    print("="*80)

    old_code = """def calculate(a, b):
    return a + b

result = calculate(x, y)"""

    new_code = """def calculate(a, b):
    return a + b

result = calculate(x, y, z)"""

    print(f"Old:\n{old_code}\n")
    print(f"New:\n{new_code}")

    old_nodes = parse_semiformal(old_code)
    new_nodes = parse_semiformal(new_code)

    result = classify_edit_scenario(old_code, new_code, old_nodes, new_nodes)

    print(f"\nStrategy: {result['strategy']}")
    print(f"Reason: {result['reason']}")

    # Should be direct or hybrid, but definitely not pure LLM
    if result['strategy'] in ('direct', 'hybrid'):
        print(f"\n✅ PASS: Correctly identified as {result['strategy']}")
        return True
    else:
        print(f"\n❌ FAIL: Expected 'direct' or 'hybrid', got '{result['strategy']}'")
        return False


def test_6_hole_filling():
    """
    TEST: x = {prepare data}
    EXPECTED: NL or INCOMPLETE
    REASON: Contains hole syntax
    """
    print("\n" + "="*80)
    print("TEST 6: Hole syntax - Should be NL/INCOMPLETE")
    print("="*80)

    code = "x = {prepare data}"

    print(f"Code: {code}")

    nodes = parse_semiformal(code)
    classifier = CompletenessClassifier(nodes)

    # Find hole node
    hole_nodes = [n for n in nodes if n.type == 'hole']

    if hole_nodes:
        hole_node = hole_nodes[0]
        completeness = classifier.classify(hole_node)

        print(f"\nHole classified as: {completeness.value}")

        if completeness in (NodeCompleteness.NL, NodeCompleteness.INCOMPLETE):
            print(f"\n✅ PASS: Correctly identified as {completeness.value}")
            return True
        else:
            print(f"\n❌ FAIL: Expected NL or INCOMPLETE, got {completeness.value}")
            return False
    else:
        print("\n❌ FAIL: No hole found")
        return False


def test_7_builtin_function():
    """
    TEST: len(items)
    EXPECTED: COMPLETE
    REASON: 'len' is a builtin function
    """
    print("\n" + "="*80)
    print("TEST 7: Builtin function call - Should be COMPLETE")
    print("="*80)

    code = "count = len(items)"

    print(f"Code: {code}")

    nodes = parse_semiformal(code)
    classifier = CompletenessClassifier(nodes)

    # Find function call
    call_nodes = [n for n in nodes if n.type == 'function_call']

    if call_nodes:
        call_node = call_nodes[0]
        completeness = classifier.classify(call_node)

        print(f"\nBuiltin call '{call_node.content}' classified as: {completeness.value}")

        if completeness == NodeCompleteness.COMPLETE:
            print("\n✅ PASS: Builtin correctly identified as complete")
            return True
        else:
            print(f"\n❌ FAIL: Expected COMPLETE, got {completeness.value}")
            return False
    else:
        print("\n❌ FAIL: No function call found")
        return False


def run_all_tests():
    """Run all edit detection tests"""
    print("\n" + "="*80)
    print("EDIT DETECTION AND STRATEGY TESTS")
    print("="*80)

    tests = [
        ("Add arg to print() [CRITICAL]", test_1_direct_edit_print_add_arg),
        ("Undefined function call", test_2_incomplete_function_call),
        ("Natural language", test_3_natural_language),
        ("Complete Python", test_4_complete_python),
        ("Edit defined function call", test_5_edit_with_definition),
        ("Hole syntax", test_6_hole_filling),
        ("Builtin function", test_7_builtin_function),
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n❌ Test '{name}' failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed_count}/{total_count} tests passed")

    # Highlight critical test
    critical_passed = results[0][1]  # First test is critical
    if critical_passed:
        print("\n" + "="*80)
        print("🎉 CRITICAL TEST PASSED!")
        print("print(output) → print(output, x) is now a DIRECT edit")
        print("NO MORE UNNECESSARY LLM CALLS FOR SIMPLE EDITS!")
        print("="*80)
    else:
        print("\n" + "="*80)
        print("❌ CRITICAL TEST FAILED")
        print("print(output) → print(output, x) still triggers LLM")
        print("Need to fix edit routing!")
        print("="*80)

    return passed_count == total_count


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
