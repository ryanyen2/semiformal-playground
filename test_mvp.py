"""
Test file for MVP implementation (Phases 1-3)

Tests:
- Phase 1: Direct AST edits
- Phase 2: Placeholder support
- Phase 3: Hole syntax and LLM generation
"""

import os
import sys

sys.path.insert(0, '/home/user/semiformal-playground/backend')

from mvp_editor import BidirectionalEditor, parse_and_generate
from mvp_translator import Edit


def test_phase_1_direct_edits():
    """Test Phase 1: Direct AST edits (no LLM needed)"""
    print("\n" + "=" * 60)
    print("PHASE 1: Direct AST Edits")
    print("=" * 60)

    # Test 1: Simple variable rename
    print("\n1. Variable Rename")
    print("-" * 40)

    semiformal_code = """
result = process_data(raw_input)
print(result)
""".strip()

    editor = BidirectionalEditor()
    editor.initialize(semiformal_code)

    print(f"Initial code:\n{editor.python_code}\n")

    # Rename result -> output
    edit = Edit(
        type='identifier_rename',
        location='result',
        old_content='result',
        content='output'
    )

    result = editor.on_semiformal_edit(edit)
    print(f"After rename result -> output:\n{result['python_code']}\n")
    assert 'output' in result['python_code']
    assert 'result' not in result['python_code']
    print("✓ Rename test passed!")

    # Test 2: Operator change
    print("\n2. Operator Change")
    print("-" * 40)

    semiformal_code2 = """
x = 5 + 3
y = x * 2
""".strip()

    editor2 = BidirectionalEditor()
    editor2.initialize(semiformal_code2)
    print(f"Initial code:\n{editor2.python_code}\n")

    # Change + to -
    edit2 = Edit(
        type='operator_change',
        location='line_0',
        old_content='+',
        content='-',
        line=0
    )

    result2 = editor2.on_semiformal_edit(edit2)
    print(f"After changing + to -:\n{result2['python_code']}\n")
    assert '5 - 3' in result2['python_code'] or '5-3' in result2['python_code']
    print("✓ Operator change test passed!")

    # Test 3: Add parameter to function
    print("\n3. Add Parameter")
    print("-" * 40)

    semiformal_code3 = """
def process(data):
    return data * 2
""".strip()

    editor3 = BidirectionalEditor()
    editor3.initialize(semiformal_code3)
    print(f"Initial code:\n{editor3.python_code}\n")

    # Add parameter
    edit3 = Edit(
        type='parameter_add',
        location='process',
        content='normalize'
    )

    result3 = editor3.on_semiformal_edit(edit3)
    print(f"After adding parameter:\n{result3['python_code']}\n")
    assert 'normalize' in result3['python_code']
    print("✓ Add parameter test passed!")
    if result3.get('needs_regeneration'):
        print("  (Note: Body regeneration flagged as needed)")


def test_phase_2_placeholders():
    """Test Phase 2: Placeholder support"""
    print("\n" + "=" * 60)
    print("PHASE 2: Placeholder Support")
    print("=" * 60)

    # Test 1: Add variable to LHS
    print("\n1. Add Variable to LHS")
    print("-" * 40)

    semiformal_code = """
x = calculate_value()
""".strip()

    editor = BidirectionalEditor()
    editor.initialize(semiformal_code)
    print(f"Initial code:\n{editor.python_code}\n")

    # Add y to LHS: x = ... -> x, y = ...
    edit = Edit(
        type='identifier_add_lhs',
        location='line_0',
        content='y',
        line=0
    )

    result = editor.on_semiformal_edit(edit)
    print(f"After adding y to LHS:\n{result['python_code']}\n")
    assert 'x, y' in result['python_code'] or 'x,y' in result['python_code']
    print("✓ Add variable to LHS test passed!")
    if result.get('needs_regeneration'):
        print("  (Note: RHS regeneration flagged as needed)")


def test_phase_3_holes():
    """Test Phase 3: Hole syntax and LLM generation"""
    print("\n" + "=" * 60)
    print("PHASE 3: Hole Syntax and LLM Generation")
    print("=" * 60)

    api_key = os.getenv('OPENAI_API_KEY')

    if not api_key:
        print("\n⚠ Skipping Phase 3 tests - OPENAI_API_KEY not set")
        print("  Set OPENAI_API_KEY environment variable to test LLM features")
        return

    # Test 1: Natural language assignment
    print("\n1. Natural Language Assignment")
    print("-" * 40)

    semiformal_code = """
result = process_data(raw_input)
x = split dataset into training and test sets
print(x)
""".strip()

    editor = BidirectionalEditor(openai_api_key=api_key)
    result = editor.initialize(semiformal_code)

    print(f"Semiformal code:\n{semiformal_code}\n")
    print(f"Generated Python:\n{result['python_code']}\n")
    print(f"Nodes parsed: {len(result['nodes'])}")
    print(f"Mappings created: {len(result['mappings'])}")
    print("✓ NL assignment test completed!")

    # Test 2: Hole without hint
    print("\n2. Empty Hole: {}")
    print("-" * 40)

    semiformal_code2 = """
data = {}
model = train_model(data)
""".strip()

    editor2 = BidirectionalEditor(openai_api_key=api_key)
    result2 = editor2.initialize(semiformal_code2)

    print(f"Semiformal code:\n{semiformal_code2}\n")
    print(f"Generated Python:\n{result2['python_code']}\n")
    print("✓ Empty hole test completed!")

    # Test 3: Hole with hint
    print("\n3. Hole with Hint: {use pandas}")
    print("-" * 40)

    semiformal_code3 = """
df = {use pandas to read CSV}
print(df.head())
""".strip()

    editor3 = BidirectionalEditor(openai_api_key=api_key)
    result3 = editor3.initialize(semiformal_code3)

    print(f"Semiformal code:\n{semiformal_code3}\n")
    print(f"Generated Python:\n{result3['python_code']}\n")
    print("✓ Hole with hint test completed!")

    # Test 4: Fill hole dynamically
    print("\n4. Dynamic Hole Filling")
    print("-" * 40)

    semiformal_code4 = """
data = None
result = process(data)
""".strip()

    editor4 = BidirectionalEditor(openai_api_key=api_key)
    editor4.initialize(semiformal_code4)

    print(f"Initial code:\n{editor4.python_code}\n")

    # Fill the hole on line 0
    fill_result = editor4.fill_hole(
        line_num=0,
        hint="load data from CSV file",
        target_var="data"
    )

    print(f"After filling hole:\n{fill_result['python_code']}\n")
    print("✓ Dynamic hole filling test completed!")


def test_integrated_workflow():
    """Test integrated workflow with multiple edits"""
    print("\n" + "=" * 60)
    print("INTEGRATED WORKFLOW TEST")
    print("=" * 60)

    # Start with semiformal code
    semiformal_code = """
data = load_dataset()
x, y = split_data(data)
model = train_model(x, y)
result = evaluate(model, x, y)
print(result)
""".strip()

    print(f"\nInitial semiformal code:\n{semiformal_code}\n")

    editor = BidirectionalEditor()
    editor.initialize(semiformal_code)

    print(f"Generated Python:\n{editor.python_code}\n")

    # Edit 1: Rename load_dataset -> load_csv_dataset
    print("Edit 1: Rename load_dataset -> load_csv_dataset")
    edit1 = Edit(
        type='identifier_rename',
        location='load_dataset',
        old_content='load_dataset',
        content='load_csv_dataset'
    )
    result1 = editor.on_semiformal_edit(edit1)
    print(f"Result:\n{result1['python_code']}\n")

    # Edit 2: Add parameter to train_model
    print("Edit 2: Add 'epochs' parameter to train_model")
    edit2 = Edit(
        type='parameter_add',
        location='train_model',
        content='epochs'
    )
    result2 = editor.on_semiformal_edit(edit2)
    print(f"Result:\n{result2['python_code']}\n")

    # Edit 3: Change operator
    print("Edit 3: Insert validation statement")
    edit3 = Edit(
        type='statement_insert',
        location='line_2',
        content='assert model is not None',
        line=2,
        metadata={'indent': 0}
    )
    result3 = editor.on_semiformal_edit(edit3)
    print(f"Final result:\n{result3['python_code']}\n")

    print("✓ Integrated workflow test completed!")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("MVP IMPLEMENTATION TEST SUITE")
    print("Testing Phases 1-3")
    print("=" * 60)

    try:
        # Phase 1: Direct edits (no LLM required)
        test_phase_1_direct_edits()

        # Phase 2: Placeholder support
        test_phase_2_placeholders()

        # Phase 3: Hole syntax and LLM (requires API key)
        test_phase_3_holes()

        # Integrated workflow
        test_integrated_workflow()

        print("\n" + "=" * 60)
        print("ALL TESTS COMPLETED SUCCESSFULLY! ✓")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
