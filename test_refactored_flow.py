#!/usr/bin/env python3
"""
Test script for refactored edit flow.

Tests:
1. Backend edit type inference
2. Direct edit (Python statement) - should NOT lose code
3. NL/hole edit - should trigger LLM generation
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from edit_router import Edit, EditTypeInferrer, EditTranslator
from edit_operations import DirectEditOperations
from generator import CodeGenerator
from parser import SemiformalParser


def test_edit_type_inference():
    """Test that backend correctly infers edit types"""
    print("\n=== Test 1: Edit Type Inference ===")
    
    inferrer = EditTypeInferrer()
    
    # Test Python statement
    edit1 = Edit(location="0", content="x = 5", line=0)
    type1 = inferrer.infer_edit_type(edit1, "x = 5")
    print(f"✓ Python assignment: {type1}")
    assert 'python' in type1.lower()
    
    # Test identifier rename
    edit2 = Edit(location="0", content="y = 5", old_content="x = 5", line=0)
    type2 = inferrer.infer_edit_type(edit2, "y = 5", "x = 5")
    print(f"✓ Identifier rename: {type2}")
    
    # Test NL edit
    edit3 = Edit(location="0", content="x = load the data", line=0)
    type3 = inferrer.infer_edit_type(edit3, "x = load the data")
    print(f"✓ NL assignment: {type3}")
    assert 'nl' in type3.lower()
    
    # Test hole edit (with hint text - not valid Python)
    edit4 = Edit(location="0", content="x = {load data}", line=0)
    type4 = inferrer.infer_edit_type(edit4, "x = {load data}")
    print(f"✓ Hole edit: {type4}")
    assert 'hole' in type4.lower() or 'nl' in type4.lower()  # Either hole or NL is acceptable
    
    print("✅ All inference tests passed!")


def test_direct_edit_no_code_loss():
    """Test that direct edits don't lose surrounding code"""
    print("\n=== Test 2: Direct Edit - No Code Loss ===")
    
    # Initial Python code with multiple lines
    python_code = """x = 1
y = 2
z = 3
result = x + y + z"""
    
    print("Initial code:")
    print(python_code)
    print()
    
    # Edit line 1 (y = 2 → y = 20)
    direct_ops = DirectEditOperations()
    result = direct_ops.replace_statement(python_code, 1, "y = 20")
    
    print("After editing line 1 (y = 2 → y = 20):")
    print(result.new_code)
    print()
    
    # Verify all lines are present
    lines = result.new_code.split('\n')
    assert len(lines) == 4, f"Expected 4 lines, got {len(lines)}"
    assert "x = 1" in lines[0], "Line 0 should be preserved"
    assert "y = 20" in lines[1], "Line 1 should be updated"
    assert "z = 3" in lines[2], "Line 2 should be preserved"
    assert "result" in lines[3], "Line 3 should be preserved"
    
    print("✅ No code loss - all lines preserved!")


def test_full_edit_flow():
    """Test full edit flow: parse → direct edit → verify"""
    print("\n=== Test 3: Full Edit Flow ===")
    
    # Parse semiformal code
    semiformal_code = """x = 1
y = 2
z = x + y"""
    
    parser = SemiformalParser()
    nodes = parser.parse(semiformal_code)
    print(f"Parsed {len(nodes)} nodes")
    
    # Generate initial Python (without LLM, should just return the Python as-is)
    generator = CodeGenerator(openai_api_key=None, generate_implementations=False)
    python_code, mappings = generator.generate_with_mapping(nodes, semiformal_code, existing_python="")
    
    print(f"Generated Python code ({len(python_code.splitlines())} lines):")
    print(python_code)
    print()
    
    # Create translator
    translator = EditTranslator(mappings, generator, nodes=nodes)
    
    # Make a direct edit (change line 1: y = 2 → y = 20)
    edit = Edit(
        location="1",
        content="y = 20",
        old_content="y = 2",
        line=1
    )
    
    result = translator.semiformal_to_python(edit, semiformal_code, python_code)
    
    print(f"Edit result: {result.message}")
    print(f"Success: {result.success}")
    print(f"Updated Python code:")
    print(result.new_code)
    print()
    
    # Verify
    lines = result.new_code.split('\n')
    assert "y = 20" in result.new_code, "Edit should be applied"
    assert "x = 1" in result.new_code, "Other lines should be preserved"
    assert "z = x + y" in result.new_code, "Other lines should be preserved"
    
    print("✅ Full edit flow successful!")


def test_operator_change():
    """Test operator change edit"""
    print("\n=== Test 4: Operator Change ===")
    
    python_code = """x = 1
y = 2
z = x + y"""
    
    direct_ops = DirectEditOperations()
    result = direct_ops.change_operator(python_code, 2, "+", "*")
    
    print("After changing + to *:")
    print(result.new_code)
    print()
    
    assert "z = x * y" in result.new_code, "Operator should be changed"
    assert "x = 1" in result.new_code, "Other lines preserved"
    assert "y = 2" in result.new_code, "Other lines preserved"
    assert len(result.new_code.split('\n')) == 3, "Should have 3 lines"
    
    print("✅ Operator change successful!")


def test_identifier_rename():
    """Test identifier rename"""
    print("\n=== Test 5: Identifier Rename ===")
    
    python_code = """x = 1
y = 2
z = x + y
print(z)"""
    
    direct_ops = DirectEditOperations()
    result = direct_ops.rename_identifier(python_code, "z", "result")
    
    print("After renaming z → result:")
    print(result.new_code)
    print()
    
    assert "result = x + y" in result.new_code, "Variable definition renamed"
    assert "print(result)" in result.new_code, "Variable usage renamed"
    assert "z" not in result.new_code or "z" in "result", "Old name should be gone"
    assert len(result.new_code.split('\n')) == 4, "Should have 4 lines"
    
    print("✅ Identifier rename successful!")


if __name__ == "__main__":
    try:
        test_edit_type_inference()
        test_direct_edit_no_code_loss()
        test_operator_change()
        test_identifier_rename()
        test_full_edit_flow()
        
        print("\n" + "="*50)
        print("🎉 ALL TESTS PASSED! 🎉")
        print("="*50)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

