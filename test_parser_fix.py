#!/usr/bin/env python3
"""
Test script to verify parser and generator fixes.
"""

import sys
sys.path.insert(0, '/home/user/semiformal-playground/backend')

from parser import parse_incomplete_python

# Test case from the user's example
test_code = """result = process_data(raw_input)
x = split dataset into training and test sets
output = transform(x)
print(result, x, output)"""

print("=" * 60)
print("TEST: Parser - NL Text Replacement")
print("=" * 60)
print("\nInput code:")
print(test_code)
print("\n" + "=" * 60)

# Parse the code
result = parse_incomplete_python(test_code)

print("\nAnnotated code (after parsing):")
print(result['annotated_code'])
print("\n" + "=" * 60)

print("\nIncomplete parts found:")
for part in result['incomplete_parts']:
    print(f"  - Type: {part['type']}, Name: {part['name']}, Line: {part['line']}")
    if part['value']:
        print(f"    Value: {part['value']}")

print("\n" + "=" * 60)
print("\nStubs created:")
for stub in result['stubs']:
    print(f"  - Type: {stub['type']}, Name: {stub['name']}")
    print(f"    Code: {stub['code']}")

print("\n" + "=" * 60)
print("VERIFICATION:")
print("=" * 60)

# Verify no duplicate lines
lines = result['annotated_code'].split('\n')
nl_line = "x = split dataset into training and test sets"
count = sum(1 for line in lines if nl_line in line and '...' not in line)
print(f"✓ Original NL text line occurrences: {count} (should be 0)")

placeholder_count = sum(1 for line in lines if 'x = ...' in line and 'split dataset' in line)
print(f"✓ Placeholder line occurrences: {placeholder_count} (should be 1)")

# Check for function stubs
process_data_stub = any('def process_data(' in line for line in lines)
transform_stub = any('def transform(' in line for line in lines)
print(f"✓ process_data stub created: {process_data_stub}")
print(f"✓ transform stub created: {transform_stub}")

print("\n" + "=" * 60)
