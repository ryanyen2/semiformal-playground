"""
Test with the USER'S EXACT example to verify mappings are correct
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from improved_mapper import create_improved_mappings


def test_user_exact_example():
    """Test with user's exact LLM-generated code"""

    semiformal_code = """result = load dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)"""

    # User's actual LLM-generated code (with duplicates!)
    generated_code = """from sklearn.model_selection import train_test_split
from typing import Tuple, Any
import pandas as pd

def transform(result: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    \"\"\"Transforms dataset and splits it into train and test sets.\"\"\"
    if not isinstance(result, pd.DataFrame):
        raise ValueError('Input must be a pandas DataFrame.')
    transformed_data = result.fillna(result.median())
    features = transformed_data.iloc[:, :-1]
    target = transformed_data.iloc[:, -1]
    X_train, X_test, y_train, y_test = train_test_split(features, target, test_size=0.2, random_state=42)
    return (X_train, X_test, y_train, y_test)

import pandas as pd
from sklearn.model_selection import train_test_split

# Load the dataset
data = pd.read_csv('data.csv')

# Process the dataset (example: dropping missing values)
processed_data = data.dropna()

# Assign processed data to result
result = processed_data

# Transform and split the data
output = transform(result)
x, y = train_test_split(result, test_size=0.2, random_state=42)

print(output)
output = transform(result)
from sklearn.model_selection import train_test_split

x, y = train_test_split(output, test_size=0.2, random_state=42)
print(output)"""

    print("="*80)
    print("SEMIFORMAL CODE:")
    print("="*80)
    for i, line in enumerate(semiformal_code.split('\n')):
        print(f"Line {i}: {line}")

    print("\n" + "="*80)
    print("GENERATED CODE (36 lines, with duplicates):")
    print("="*80)
    for i, line in enumerate(generated_code.split('\n'), 1):
        print(f"{i:2}: {line}")

    # Parse
    nodes = parse_semiformal(semiformal_code)

    print("\n" + "="*80)
    print("INTENT NODES:")
    print("="*80)
    for i, node in enumerate(nodes):
        is_def = node.metadata.get('is_definition', False)
        print(f"Node {i:2}: {node.type:15} '{node.content[:30]:30}' line={node.span[0]} def={is_def}")

    # Create mappings
    mappings = create_improved_mappings(nodes, generated_code)

    print("\n" + "="*80)
    print("IMPROVED MAPPINGS:")
    print("="*80)

    # Expected correct mappings (from user's example and analysis)
    expected = {
        0: 25,   # result (def) → line 25: result = processed_data
        1: 25,   # load dataset (NL) → line 25
        2: 25,   # and (NL) → line 25
        3: 25,   # process it (NL) → line 25
        4: 28,   # output (def) → line 28: output = transform(result)
        5: 28,   # result (ref) → line 28
        6: 28,   # transform → line 28
        7: 29,   # x (def) → line 29: x, y = train_test_split
        8: 29,   # y (def) → line 29
        9: 29,   # hole → line 29
        10: 31,  # output (ref) → line 31: print(output)
        11: 31,  # print → line 31
        12: 31,  # expr_stmt → line 31
    }

    correct = 0
    total = 0

    for mapping in mappings:
        # Find intent node
        node_id = mapping.node_id
        intent_node = next((n for n in nodes if n.id == node_id), None)
        if not intent_node:
            continue

        node_idx = nodes.index(intent_node)
        gen_line = mapping.slices[0].line_start
        snippet = mapping.slices[0].code[:60]

        if node_idx in expected:
            total += 1
            exp_line = expected[node_idx]

            if gen_line == exp_line:
                print(f"✓ Node {node_idx:2} ({intent_node.type:12} line {intent_node.span[0]}) → gen line {gen_line:2} CORRECT")
                correct += 1
            else:
                print(f"❌ Node {node_idx:2} ({intent_node.type:12} line {intent_node.span[0]}) → gen line {gen_line:2} (expected {exp_line:2})")
                print(f"   Got: {snippet}")
        else:
            print(f"  Node {node_idx:2} ({intent_node.type:12} line {intent_node.span[0]}) → gen line {gen_line:2}")

    print("\n" + "="*80)
    print("SUMMARY:")
    print("="*80)
    print(f"Correct mappings: {correct}/{total}")
    print(f"Accuracy: {100 * correct / total if total > 0 else 0:.1f}%")

    # Check all nodes mapped
    mapped_count = len(mappings)
    total_nodes = len(nodes)
    print(f"Nodes mapped: {mapped_count}/{total_nodes}")

    if mapped_count == total_nodes and correct == total:
        print("\n✅ ALL NODES MAPPED CORRECTLY!")
        return True
    elif mapped_count == total_nodes:
        print(f"\n⚠️  All nodes mapped but {total - correct} have wrong lines")
        return False
    else:
        print(f"\n❌ Missing {total_nodes - mapped_count} mappings")
        return False


if __name__ == "__main__":
    success = test_user_exact_example()
    sys.exit(0 if success else 1)
