"""
Test fine-grained mapper with user's exact example
"""

import sys
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from fine_grained_mapper import FineGrainedMapper


def test_fine_grained_mapping():
    """Test with user's exact generated code"""

    semiformal_code = """result = load dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output, x)"""

    # User's actual generated code (with duplicates)
    generated_code = """from sklearn.model_selection import train_test_split
from typing import Tuple, Any
import pandas as pd

def transform(result: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    \"\"\"Transforms dataset by separating features and target.\"\"\"
    try:
        features = result.iloc[:, :-1]
        target = result.iloc[:, -1]
        return (features, target)
    except Exception as e:
        raise ValueError('Invalid input data format.') from e

import pandas as pd
from sklearn.model_selection import train_test_split

# Load the dataset
data = pd.read_csv('your_dataset.csv')

# Process the dataset (example: drop missing values)
processed_data = data.dropna()

result = processed_data

output = transform(result)

x, y = train_test_split(result, test_size=0.2)

print(output, x)
output = transform(result)
from sklearn.model_selection import train_test_split

x, y = train_test_split(output, test_size=0.2, random_state=42)
print(output, x)"""

    print("="*80)
    print("SEMIFORMAL CODE:")
    print("="*80)
    for i, line in enumerate(semiformal_code.split('\n')):
        print(f"Line {i}: {line}")

    print("\n" + "="*80)
    print("GENERATED CODE:")
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

    # Create fine-grained mappings
    mapper = FineGrainedMapper(generated_code)
    mappings = mapper.map_all_nodes(nodes)

    print("\n" + "="*80)
    print("FINE-GRAINED MAPPINGS:")
    print("="*80)

    # Expected mappings (what we SHOULD get)
    expectations = {
        'result (def)': (23, 0, 6, 'result'),
        'load': (18, None, None, 'pd.read_csv'),  # Should map to the call
        'dataset': (18, None, None, 'your_dataset.csv'),  # Should map to the string
        'process it': (21, None, None, 'dropna'),  # Should map to dropna call
        'output (def)': (25, 0, 6, 'output'),
        'result (ref in line 3)': (25, 18, 24, 'result'),
        'transform': (25, None, None, 'transform'),
        'x (def)': (27, 0, 1, 'x'),
        'y (def)': (27, 3, 4, 'y'),
        'output (ref in print)': (29, 6, 12, 'output'),  # NOT the whole print!
        'x (ref in print)': (29, 14, 15, 'x'),  # NOT the whole print!
        'print': (29, 0, None, 'print'),
    }

    issues = []

    for mapping in mappings:
        # Find intent node
        intent_node = next((n for n in nodes if n.id == mapping.node_id), None)
        if not intent_node:
            continue

        node_type = intent_node.type
        content = intent_node.content[:30]
        line = mapping.line
        col_start = mapping.col_start
        col_end = mapping.col_end
        code_text = mapping.code_text
        map_type = mapping.mapping_type

        print(f"{node_type:15} '{content:30}' → line {line:2} col {col_start:2}-{col_end:2} '{code_text:30}' ({map_type})")

        # Check specific important cases
        if content == 'load' and 'read_csv' not in code_text:
            issues.append(f"'load' should map to read_csv call, got: {code_text}")

        if content == 'dataset' and 'your_dataset.csv' not in code_text and 'csv' not in code_text:
            issues.append(f"'dataset' should map to filename, got: {code_text}")

        if 'process' in content and 'dropna' not in code_text:
            issues.append(f"'process it' should map to dropna call, got: {code_text}")

        if content == 'output' and node_type == 'identifier' and intent_node.metadata.get('role') == 'reference':
            # This is the output ref in print(output, x)
            if code_text != 'output':
                issues.append(f"'output' reference should map to just 'output', got: {code_text}")
            if col_start != 6:
                issues.append(f"'output' in print should start at col 6, got: {col_start}")

    print("\n" + "="*80)
    print("ANALYSIS:")
    print("="*80)

    if issues:
        print(f"\n❌ Found {len(issues)} mapping issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ All critical mappings look good!")

    # Check coverage
    print(f"\nNodes mapped: {len(mappings)}/{len(nodes)}")

    return len(issues) == 0


if __name__ == "__main__":
    success = test_fine_grained_mapping()
    sys.exit(0 if success else 1)
