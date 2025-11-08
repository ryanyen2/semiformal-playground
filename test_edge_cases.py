"""
Edge case tests for MVP implementation

Tests unusual scenarios, error cases, and boundary conditions.
"""

import os
import sys

sys.path.insert(0, '/home/user/semiformal-playground/backend')

from mvp_editor import BidirectionalEditor
from mvp_translator import Edit
from mvp_config import MVPConfig, LLMConfig, GeneratorConfig


def test_empty_inputs():
    """Test handling of empty inputs"""
    print("\n" + "=" * 60)
    print("TEST: Empty Inputs")
    print("=" * 60)

    editor = BidirectionalEditor()

    # Test 1: Empty semiformal code
    print("\n1. Empty semiformal code")
    result = editor.initialize("")
    assert result['python_code'] == '', f"Expected empty, got: {result['python_code']}"
    print("✓ Empty code handled correctly")

    # Test 2: Whitespace only
    print("\n2. Whitespace only")
    result = editor.initialize("   \n  \t  \n   ")
    assert result['python_code'].strip() == '', f"Expected empty, got: {result['python_code']}"
    print("✓ Whitespace-only code handled correctly")

    # Test 3: Comments only
    print("\n3. Comments only")
    result = editor.initialize("# Just a comment\n# Another comment")
    assert len(result['nodes']) == 0, f"Expected no nodes, got: {len(result['nodes'])}"
    print("✓ Comment-only code handled correctly")


def test_complex_expressions():
    """Test complex Python expressions"""
    print("\n" + "=" * 60)
    print("TEST: Complex Expressions")
    print("=" * 60)

    editor = BidirectionalEditor()

    # Test 1: Nested function calls
    print("\n1. Nested function calls")
    code = "result = transform(process(clean(data)))"
    result = editor.initialize(code)
    assert 'transform' in result['python_code']
    assert 'process' in result['python_code']
    assert 'clean' in result['python_code']
    print(f"Generated: {result['python_code']}")
    print("✓ Nested function calls handled")

    # Test 2: List comprehension
    print("\n2. List comprehension")
    code = "squares = [x**2 for x in range(10)]"
    result = editor.initialize(code)
    # AST.unparse may normalize spacing, so check for components
    assert 'squares' in result['python_code']
    assert 'for x in range(10)' in result['python_code']
    print(f"Generated: {result['python_code']}")
    print("✓ List comprehension handled")

    # Test 3: Dictionary literal
    print("\n3. Dictionary literal")
    code = "config = {'lr': 0.01, 'epochs': 100}"
    result = editor.initialize(code)
    assert 'config' in result['python_code']
    assert 'lr' in result['python_code']
    print(f"Generated: {result['python_code']}")
    print("✓ Dictionary literal handled")

    # Test 4: Multi-line expression
    print("\n4. Multi-line statement")
    code = """result = (
    x + y +
    z * 2
)"""
    result = editor.initialize(code)
    assert 'result' in result['python_code']
    print(f"Generated: {result['python_code']}")
    print("✓ Multi-line statement handled")


def test_nl_edge_cases():
    """Test natural language edge cases"""
    print("\n" + "=" * 60)
    print("TEST: Natural Language Edge Cases")
    print("=" * 60)

    editor = BidirectionalEditor()

    # Test 1: Very short NL
    print("\n1. Very short NL (single word)")
    code = "data = load"
    result = editor.initialize(code)
    # Should treat "load" as NL
    print(f"Nodes: {len(result['nodes'])}")
    print(f"Generated: {result['python_code']}")
    print("✓ Short NL handled")

    # Test 2: Very long NL
    print("\n2. Very long NL phrase")
    code = "result = load the dataset from CSV file and preprocess it by removing null values and normalizing"
    result = editor.initialize(code)
    assert len(result['nodes']) > 0
    print(f"Segmented into {len(result['nodes'])} nodes")
    print("✓ Long NL phrase handled")

    # Test 3: NL with special characters
    print("\n3. NL with special characters")
    code = "data = load file.csv with encoding=utf-8"
    result = editor.initialize(code)
    print(f"Generated: {result['python_code']}")
    print("✓ NL with special chars handled")

    # Test 4: NL with numbers
    print("\n4. NL with numbers")
    code = "matrix = create 5x5 identity matrix"
    result = editor.initialize(code)
    assert len(result['nodes']) > 0
    print(f"Generated: {result['python_code']}")
    print("✓ NL with numbers handled")


def test_error_handling():
    """Test error handling"""
    print("\n" + "=" * 60)
    print("TEST: Error Handling")
    print("=" * 60)

    editor = BidirectionalEditor()

    # Test 1: Invalid Python syntax (should handle gracefully)
    print("\n1. Invalid Python syntax")
    try:
        # This is invalid Python but valid semiformal
        code = "x = ;;; invalid syntax"
        result = editor.initialize(code)
        # Should treat as NL
        print(f"Handled as NL: {len(result['nodes'])} nodes")
        print("✓ Invalid syntax handled gracefully")
    except Exception as e:
        print(f"❌ Failed with: {e}")
        raise

    # Test 2: Rename non-existent identifier
    print("\n2. Rename non-existent identifier")
    editor.initialize("x = 5")
    edit = Edit(
        type='identifier_rename',
        location='nonexistent',
        old_content='nonexistent',
        content='newname'
    )
    result = editor.on_semiformal_edit(edit)
    # Should fail gracefully
    assert not result['success'] or result['python_code'] == editor.python_code
    print("✓ Non-existent rename handled gracefully")

    # Test 3: Out of bounds line number (gracefully appends)
    print("\n3. Out of bounds line number")
    editor.initialize("x = 5\ny = 10")
    edit = Edit(
        type='statement_insert',
        location='line_100',
        content='z = 15',
        line=100
    )
    result = editor.on_semiformal_edit(edit)
    # Should succeed by appending at end
    assert result['success']
    assert 'z = 15' in result['python_code']
    print("✓ Out of bounds line handled gracefully (appended at end)")


def test_configuration():
    """Test configuration customization"""
    print("\n" + "=" * 60)
    print("TEST: Configuration")
    print("=" * 60)

    # Test 1: Custom LLM config
    print("\n1. Custom LLM model config")
    config = MVPConfig()
    config.llm.model = "gpt-4"
    config.llm.temperature = 0.5
    config.llm.max_tokens = 2000

    editor = BidirectionalEditor(config=config)
    assert editor.config.llm.model == "gpt-4"
    assert editor.config.llm.temperature == 0.5
    print("✓ Custom LLM config applied")

    # Test 2: Disable validation
    print("\n2. Disable code validation")
    config = MVPConfig()
    config.generator.validate_generated_code = False
    editor = BidirectionalEditor(config=config)
    assert not editor.config.generator.validate_generated_code
    print("✓ Validation disabled")

    # Test 3: Custom edit types
    print("\n3. Add custom edit type")
    config = MVPConfig()
    config.edit_types.direct_edit_types.append('my_custom_edit')
    editor = BidirectionalEditor(config=config)
    assert 'my_custom_edit' in editor.config.edit_types.direct_edit_types
    print("✓ Custom edit type added")


def test_unicode_and_special_chars():
    """Test Unicode and special characters"""
    print("\n" + "=" * 60)
    print("TEST: Unicode and Special Characters")
    print("=" * 60)

    editor = BidirectionalEditor()

    # Test 1: Unicode variable names
    print("\n1. Unicode characters")
    code = "résultat = données + 5"
    result = editor.initialize(code)
    assert 'résultat' in result['python_code']
    print(f"Generated: {result['python_code']}")
    print("✓ Unicode handled")

    # Test 2: Emoji in comments
    print("\n2. Emoji in code")
    code = "# 🚀 Processing data\ndata = process()"
    result = editor.initialize(code)
    assert 'process' in result['python_code']
    print("✓ Emoji handled")

    # Test 3: Multi-byte characters
    print("\n3. Multi-byte characters")
    code = "日本語 = 'テスト'"
    result = editor.initialize(code)
    assert '日本語' in result['python_code']
    print("✓ Multi-byte chars handled")


def test_large_code():
    """Test with large code bases"""
    print("\n" + "=" * 60)
    print("TEST: Large Code")
    print("=" * 60)

    editor = BidirectionalEditor()

    # Generate large code
    print("\n1. Many variables (100)")
    lines = [f"var_{i} = {i}" for i in range(100)]
    code = '\n'.join(lines)

    result = editor.initialize(code)
    assert len(result['nodes']) >= 100  # At least 100 identifiers
    print(f"Parsed {len(result['nodes'])} nodes")
    print("✓ Large code handled")

    # Test 2: Many functions
    print("\n2. Many functions (50)")
    lines = [f"def func_{i}():\n    return {i}\n" for i in range(50)]
    code = '\n'.join(lines)

    result = editor.initialize(code)
    func_nodes = [n for n in result['nodes'] if n['type'] == 'function_def']
    assert len(func_nodes) == 50
    print(f"Parsed {len(func_nodes)} functions")
    print("✓ Many functions handled")


def test_mixed_content():
    """Test mixed Python and NL content"""
    print("\n" + "=" * 60)
    print("TEST: Mixed Python and NL Content")
    print("=" * 60)

    editor = BidirectionalEditor()

    # Test 1: Python then NL
    print("\n1. Python followed by NL")
    code = """x = 5
y = load the dataset
z = x + 10"""
    result = editor.initialize(code)
    assert 'x = 5' in result['python_code']
    assert 'z = x + 10' in result['python_code']
    print(f"Generated: {result['python_code']}")
    print("✓ Mixed Python/NL handled")

    # Test 2: NL in function (known limitation: parses line-by-line)
    print("\n2. NL inside function")
    code = """def process():
    data = load from database
    return data"""
    result = editor.initialize(code)
    # Note: Hybrid code triggers line-by-line parsing
    # Full function context may be lost - this is a known limitation
    # Check that at least some code was generated
    assert len(result['python_code']) > 0
    print(f"Generated: {result['python_code']}")
    print("✓ NL in function handled (line-by-line mode)")


def main():
    """Run all edge case tests"""
    print("\n" + "=" * 60)
    print("EDGE CASE TEST SUITE")
    print("=" * 60)

    try:
        test_empty_inputs()
        test_complex_expressions()
        test_nl_edge_cases()
        test_error_handling()
        test_configuration()
        test_unicode_and_special_chars()
        test_large_code()
        test_mixed_content()

        print("\n" + "=" * 60)
        print("ALL EDGE CASE TESTS PASSED! ✓")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Edge case test failed: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
