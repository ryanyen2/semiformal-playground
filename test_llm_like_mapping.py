"""
Test with LLM-like generated code (complex, duplicated, out of order)
to see if mappings are actually correct
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from tree_mapper import TreeMapper, MappingAdapter


def test_llm_like_code():
    """Test with messy LLM-generated code like the user's example"""

    semiformal_code = """result = load dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)"""

    # Simulate messy LLM-generated code (like user's example)
    # This has:
    # - Imports at top (not in semiformal)
    # - A transform function definition (generated from incomplete call)
    # - Duplicate imports later
    # - Code in different order
    # - Multiple occurrences of same variables
    generated_code = """from sklearn.model_selection import train_test_split
from typing import Tuple
import pandas as pd

def transform(result):
    # This function was generated because user called it
    result = result.fillna(result.mean())
    X = result.iloc[:, :-1]
    y = result.iloc[:, -1]
    return train_test_split(X, y, test_size=0.2)

# Duplicate imports (bad LLM generation)
import pandas as pd

# Load dataset - corresponds to semiformal line 1
data = pd.read_csv('data.csv')
processed = data.dropna()
result = processed  # Final assignment to result

# Call transform - corresponds to semiformal line 3
output = transform(result)

# Split data - corresponds to semiformal line 5
x, y = train_test_split(output, test_size=0.2)

# Print - corresponds to semiformal line 7
print(output)"""

    print("="*80)
    print("SEMIFORMAL CODE:")
    print("="*80)
    for i, line in enumerate(semiformal_code.split('\n'), 1):
        print(f"{i:2}: {line}")

    print("\n" + "="*80)
    print("LLM-GENERATED CODE (messy, out of order, duplicated):")
    print("="*80)
    for i, line in enumerate(generated_code.split('\n'), 1):
        print(f"{i:2}: {line}")

    # Parse and map
    nodes = parse_semiformal(semiformal_code)
    mapper = TreeMapper()
    ir_tree = mapper.build_ir_tree(nodes)
    ast_tree = mapper.build_ast_tree(generated_code)
    tree_mappings = mapper.map_trees(ir_tree, ast_tree)
    code_mappings = MappingAdapter.convert_tree_mappings_to_code_mappings(
        tree_mappings,
        generated_code
    )

    print("\n" + "="*80)
    print("CHECKING MAPPINGS:")
    print("="*80)

    # Expected mappings
    expectations = {
        'result (line 1)': (17, 'result = processed'),
        'load dataset (line 1)': (15, 'data = pd.read_csv'),
        'output (line 3)': (20, 'output = transform(result)'),
        'transform (line 3)': (20, 'output = transform(result)'),
        'x (line 5)': (23, 'x, y = train_test_split'),
        'y (line 5)': (23, 'x, y = train_test_split'),
        'print (line 7)': (26, 'print(output)'),
    }

    issues = []

    for mapping in code_mappings:
        intent_node = next((n for n in nodes if n.id == mapping.node_id), None)
        if intent_node and mapping.slices:
            sf_line = intent_node.span[0]
            gen_line = mapping.slices[0].line_start
            code_snippet = mapping.slices[0].code

            node_desc = f"{intent_node.content} (line {sf_line})"

            # Check if this matches expectations
            if node_desc in expectations:
                expected_line, expected_snippet_part = expectations[node_desc]
                if gen_line == expected_line and expected_snippet_part in code_snippet:
                    print(f"✓ OK: {node_desc:30} → line {gen_line:2} {code_snippet[:50]}")
                else:
                    print(f"❌ BAD: {node_desc:30} → line {gen_line:2} (expected {expected_line:2}) {code_snippet[:50]}")
                    issues.append({
                        'node': node_desc,
                        'expected': expected_line,
                        'actual': gen_line,
                        'code': code_snippet
                    })
            else:
                print(f"  ?: {node_desc:30} → line {gen_line:2} {code_snippet[:50]}")

    print("\n" + "="*80)
    print("SUMMARY:")
    print("="*80)

    if issues:
        print(f"\n❌ Found {len(issues)} MAPPING ERRORS:\n")
        for issue in issues:
            print(f"  {issue['node']}")
            print(f"    Expected line {issue['expected']}")
            print(f"    Got line {issue['actual']}: {issue['code'][:60]}")
            print()
        print("="*80)
        print("CONCLUSION: Tree mapper is BROKEN for LLM-generated code!")
        print("="*80)
    else:
        print("\n✓ All mappings correct!")

    return len(issues) == 0


if __name__ == "__main__":
    success = test_llm_like_code()
    sys.exit(0 if success else 1)
