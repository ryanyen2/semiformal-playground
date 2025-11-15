"""
Integration Test for Completeness-Based Edit Routing

Tests that the editor properly uses CompletenessClassifier to route edits:
- Direct edits (complete Python) should NOT trigger LLM
- NL edits should trigger LLM
- Incomplete Python should use hybrid approach
"""

import sys
sys.path.insert(0, 'backend')

from editor import BidirectionalEditor
from edit_router import Edit


def test_1_direct_edit_no_llm():
    """
    TEST: Edit complete Python code (print argument add)
    EXPECTED: Direct AST edit, no LLM call
    CRITICAL: This was broken before - it triggered LLM
    """
    print("\n" + "="*80)
    print("TEST 1: Direct Edit on Complete Python (print argument add)")
    print("="*80)

    # Initialize editor with complete Python
    editor = BidirectionalEditor()
    state = editor.initialize("print(output)")

    print(f"\nInitial Python code:\n{state['python_code']}")
    print(f"Intent nodes: {len(state['nodes'])}")

    # Check if classifier is available
    if editor.translator and editor.translator.classifier:
        print("\n✓ CompletenessClassifier is available in translator")

        # Check completeness of the print call
        from completeness_classifier import NodeCompleteness
        print_nodes = [n for n in editor.intent_nodes if 'print' in n.content.lower()]
        if print_nodes:
            completeness = editor.translator.classifier.classify(print_nodes[0])
            print(f"  print() classified as: {completeness.value}")

            if completeness == NodeCompleteness.COMPLETE:
                print("  ✓ Correctly identified as complete")
            else:
                print(f"  ✗ Incorrectly classified as {completeness.value}")
                return False
        else:
            print("  ⚠ No print node found")
    else:
        print("\n⚠ CompletenessClassifier not available - check imports")
        return False

    # Simulate edit: print(output) → print(output, x)
    # In a real scenario, this would come from user editing the semiformal code
    edit = Edit(
        type='argument_add',
        location='print',
        content='x',
        old_content='print(output)',
        line=0,
        metadata={'function_name': 'print'}
    )

    print(f"\nSimulated edit: {edit.old_content} → add argument 'x'")

    # Get affected nodes
    affected = editor.translator._get_affected_nodes(edit)
    print(f"Affected nodes: {len(affected)}")

    if affected and editor.translator.classifier:
        strategy = editor.translator.classifier.get_edit_strategy(affected)
        print(f"Edit strategy: {strategy}")

        if strategy == 'direct':
            print("\n✅ PASS: Edit correctly routed to 'direct' (no LLM)")
            return True
        else:
            print(f"\n❌ FAIL: Edit routed to '{strategy}' instead of 'direct'")
            return False
    else:
        print("\n⚠ Could not determine strategy")
        return False


def test_2_nl_edit_uses_llm():
    """
    TEST: Edit natural language expression
    EXPECTED: LLM routing
    """
    print("\n" + "="*80)
    print("TEST 2: NL Edit Should Use LLM")
    print("="*80)

    editor = BidirectionalEditor()
    state = editor.initialize("data = load and preprocess dataset")

    print(f"\nInitial semiformal code: data = load and preprocess dataset")
    print(f"Intent nodes: {len(state['nodes'])}")

    if editor.translator and editor.translator.classifier:
        print("\n✓ CompletenessClassifier is available")

        # Check completeness
        nl_nodes = [n for n in editor.intent_nodes if n.type == 'nl_phrase']
        if nl_nodes:
            completeness = editor.translator.classifier.classify(nl_nodes[0])
            print(f"  NL phrase classified as: {completeness.value}")

            if completeness.value == 'nl':
                print("  ✓ Correctly identified as NL")
            else:
                print(f"  ✗ Incorrectly classified as {completeness.value}")

        # Test strategy
        affected = editor.intent_nodes[:2] if len(editor.intent_nodes) >= 2 else editor.intent_nodes
        if affected:
            strategy = editor.translator.classifier.get_edit_strategy(affected)
            print(f"\nEdit strategy for NL: {strategy}")

            if strategy == 'llm':
                print("\n✅ PASS: NL edit correctly routed to 'llm'")
                return True
            else:
                print(f"\n❌ FAIL: NL edit routed to '{strategy}' instead of 'llm'")
                return False
    else:
        print("\n⚠ CompletenessClassifier not available")
        return False


def test_3_incomplete_python():
    """
    TEST: Function call without definition
    EXPECTED: Incomplete classification
    """
    print("\n" + "="*80)
    print("TEST 3: Incomplete Python (function call without definition)")
    print("="*80)

    editor = BidirectionalEditor()
    state = editor.initialize("result = process_data(input)")

    print(f"\nSemiformal code: result = process_data(input)")
    print(f"Intent nodes: {len(state['nodes'])}")

    if editor.translator and editor.translator.classifier:
        print("\n✓ CompletenessClassifier is available")

        # Find function call node
        func_call_nodes = [n for n in editor.intent_nodes if n.type == 'function_call']
        if func_call_nodes:
            completeness = editor.translator.classifier.classify(func_call_nodes[0])
            print(f"  Function call classified as: {completeness.value}")

            if completeness.value == 'incomplete':
                print("  ✓ Correctly identified as incomplete")
                print("\n✅ PASS: Incomplete Python correctly identified")
                return True
            else:
                print(f"  ✗ Incorrectly classified as {completeness.value}")
                print("\n❌ FAIL: Should be incomplete")
                return False
    else:
        print("\n⚠ CompletenessClassifier not available")
        return False


def run_all_tests():
    """Run all integration tests"""
    print("\n" + "="*80)
    print("INTEGRATION TESTS: Completeness-Based Edit Routing")
    print("="*80)

    tests = [
        ("Direct Edit (print arg add) [CRITICAL]", test_1_direct_edit_no_llm),
        ("NL Edit Uses LLM", test_2_nl_edit_uses_llm),
        ("Incomplete Python Detection", test_3_incomplete_python),
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
    print("INTEGRATION TEST SUMMARY")
    print("="*80)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed_count}/{total_count} tests passed")

    # Highlight critical test
    if results and results[0][1]:
        print("\n" + "="*80)
        print("🎉 CRITICAL TEST PASSED!")
        print("print(output) → print(output, x) now uses DIRECT edit")
        print("NO MORE UNNECESSARY LLM CALLS!")
        print("="*80)
    else:
        print("\n" + "="*80)
        print("❌ CRITICAL TEST FAILED")
        print("Integration needs debugging")
        print("="*80)

    return passed_count == total_count


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
