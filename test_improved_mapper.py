"""
Test improved content-based mapper with LLM-like code
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from improved_mapper import create_improved_mappings


def test_improved_mapper():
    """Test improved mapper with messy LLM-generated code"""

    semiformal_code = """result = load dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)"""

    # LLM-like generated code (messy, out of order, duplicated)
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

# Load dataset - corresponds to semiformal line 1 (0-indexed: line 0)
data = pd.read_csv('data.csv')
processed = data.dropna()
result = processed  # Final assignment to result

# Call transform - corresponds to semiformal line 3 (0-indexed: line 2)
output = transform(result)

# Split data - corresponds to semiformal line 5 (0-indexed: line 4)
x, y = train_test_split(output, test_size=0.2)

# Print - corresponds to semiformal line 7 (0-indexed: line 6)
print(output)"""

    print("="*80)
    print("SEMIFORMAL CODE:")
    print("="*80)
    for i, line in enumerate(semiformal_code.split('\n')):
        print(f"Line {i}: {line}")

    print("\n" + "="*80)
    print("LLM-GENERATED CODE (messy, out of order):")
    print("="*80)
    for i, line in enumerate(generated_code.split('\n'), 1):
        print(f"{i:2}: {line}")

    # Parse semiformal
    nodes = parse_semiformal(semiformal_code)

    print("\n" + "="*80)
    print("INTENT NODES:")
    print("="*80)
    for i, node in enumerate(nodes):
        is_def = node.metadata.get('is_definition', False)
        role = node.metadata.get('role', '')
        print(f"{i:2}: {node.type:15} '{node.content:20}' line={node.span[0]} def={is_def} role={role}")

    # Create improved mappings
    mappings = create_improved_mappings(nodes, generated_code)

    print("\n" + "="*80)
    print("IMPROVED MAPPINGS:")
    print("="*80)

    # Expected correct mappings
    expectations = {
        'result': {
            'line_0_def': 18,  # result from line 0, is_definition=True → line 18
        },
        'output': {
            'line_2_def': 21,  # output from line 2, is_definition=True → line 21
        },
        'x': {
            'line_4_def': 24,  # x from line 4, is_definition=True → line 24
        },
        'y': {
            'line_4_def': 24,  # y from line 4, is_definition=True → line 24
        },
        'transform': {
            'line_2_call': 21,  # transform call from line 2 → line 21
        },
        'print': {
            'line_6_call': 27,  # print call from line 6 → line 27
        }
    }

    issues = []
    correct_count = 0

    for mapping in mappings:
        # Find the intent node
        intent_node = next((n for n in nodes if n.id == mapping.node_id), None)
        if not intent_node:
            continue

        sf_line = intent_node.span[0]
        gen_line = mapping.slices[0].line_start
        code_snippet = mapping.slices[0].code

        is_def = intent_node.metadata.get('is_definition', False)
        node_type = intent_node.type
        content = intent_node.content

        # Build expectation key
        if content in expectations:
            exp_dict = expectations[content]
            key = f"line_{sf_line}_def" if is_def else f"line_{sf_line}_call"

            if key in exp_dict:
                expected_line = exp_dict[key]

                if gen_line == expected_line:
                    print(f"✓ {content:15} (sf line {sf_line}, {node_type:12}) → gen line {gen_line:2} {code_snippet[:50]}")
                    correct_count += 1
                else:
                    print(f"❌ {content:15} (sf line {sf_line}, {node_type:12}) → gen line {gen_line:2} (expected {expected_line:2})")
                    print(f"   Got: {code_snippet}")
                    issues.append({
                        'node': content,
                        'expected': expected_line,
                        'actual': gen_line
                    })
            else:
                print(f"  {content:15} (sf line {sf_line}, {node_type:12}) → gen line {gen_line:2} {code_snippet[:50]}")
        else:
            print(f"  {content:15} (sf line {sf_line}, {node_type:12}) → gen line {gen_line:2} {code_snippet[:50]}")

    print("\n" + "="*80)
    print("SUMMARY:")
    print("="*80)

    total_expected = len([k for exp in expectations.values() for k in exp.keys()])
    print(f"\nExpected mappings: {total_expected}")
    print(f"Correct mappings: {correct_count}")
    print(f"Accuracy: {100 * correct_count / total_expected if total_expected > 0 else 0:.1f}%")

    if issues:
        print(f"\n❌ {len(issues)} mapping errors:")
        for issue in issues:
            print(f"  - {issue['node']}: expected line {issue['expected']}, got {issue['actual']}")
    else:
        print("\n✅ All critical mappings correct!")

    return len(issues) == 0


if __name__ == "__main__":
    success = test_improved_mapper()
    sys.exit(0 if success else 1)
