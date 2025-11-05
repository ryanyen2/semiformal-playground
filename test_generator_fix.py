#!/usr/bin/env python3
"""
Test script to verify generator code extraction and stub replacement logic.
"""

# Reproduce the _extract_code logic
def extract_code(response: str) -> str:
    """Extract clean Python code from LLM response."""
    response = response.strip()

    # Remove markdown code fences if present
    lines = response.split('\n')

    # Find and remove code block boundaries
    start_idx = 0
    end_idx = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('```'):
            if start_idx == 0:
                start_idx = i + 1
            else:
                end_idx = i
                break

    # If we found fences, extract only the code between them
    if start_idx > 0:
        code_lines = lines[start_idx:end_idx]
    else:
        code_lines = lines

    # Remove any remaining stray backticks or markdown
    cleaned_lines = []
    for line in code_lines:
        # Remove lines that are just backticks
        if line.strip() in ('```', '```python', '```py'):
            continue
        # Remove inline code fence artifacts
        line = line.replace('```python', '').replace('```py', '').replace('```', '')
        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines).strip()


# Reproduce the _replace_stub_with_impl logic
def replace_stub_with_impl(code: str, func_name: str, implementation: str) -> str:
    """Replace a function stub with its implementation."""
    lines = code.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is the stub definition
        if f"def {func_name}(" in line:
            # Check if next line is the ellipsis stub
            if i + 1 < len(lines) and "..." in lines[i + 1]:
                # Replace the entire stub with the implementation
                result.append(implementation)
                i += 2  # Skip both def line and ... line
                # Skip blank line after stub if present
                if i < len(lines) and not lines[i].strip():
                    i += 1
            else:
                # Not a stub, keep the line
                result.append(line)
                i += 1
        else:
            result.append(line)
            i += 1

    return '\n'.join(result)


print("=" * 60)
print("TEST: Generator Code Extraction")
print("=" * 60)

test_cases = [
    (
        "```python\ntrain_test_split(dataset, test_size=0.2, random_state=42)\n```",
        "train_test_split(dataset, test_size=0.2, random_state=42)"
    ),
    (
        "```\ntrain_test_split(dataset, test_size=0.2, random_state=42)\n```",
        "train_test_split(dataset, test_size=0.2, random_state=42)"
    ),
    (
        "train_test_split(dataset, test_size=0.2, random_state=42)",
        "train_test_split(dataset, test_size=0.2, random_state=42)"
    ),
    (
        "Here's the code:\n```python\ndef foo():\n    return 42\n```",
        "def foo():\n    return 42"
    ),
]

print("\nTesting extract_code:")
all_passed = True
for i, (input_text, expected) in enumerate(test_cases, 1):
    result = extract_code(input_text)
    passed = result == expected
    all_passed = all_passed and passed
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"\n  Test {i}: {status}")
    if not passed:
        print(f"    Input: {repr(input_text)}")
        print(f"    Expected: {repr(expected)}")
        print(f"    Got: {repr(result)}")

print("\n" + "=" * 60)
print("TEST: Function Stub Replacement")
print("=" * 60)

# Test _replace_stub_with_impl
test_code = """def process_data(arg0):
    ...

result = process_data(raw_input)

def transform(arg0):
    ...

output = transform(x)"""

implementation = """def process_data(data):
    # Process the input data
    cleaned = data.strip()
    return cleaned.upper()"""

print("\nOriginal code with stub:")
print(test_code)

result = replace_stub_with_impl(test_code, "process_data", implementation)

print("\n" + "-" * 60)
print("After stub replacement:")
print(result)

# Verify the stub was replaced
has_stub = "def process_data(arg0):" in result and "..." in result
has_impl = "cleaned = data.strip()" in result
print("\n" + "-" * 60)
print("VERIFICATION:")
print(f"  ✓ Stub removed: {not has_stub}")
print(f"  ✓ Implementation inserted: {has_impl}")
print(f"  ✓ transform stub still intact: {'def transform(arg0):' in result}")

if all_passed and not has_stub and has_impl:
    print("\n" + "=" * 60)
    print("✓ ALL TESTS PASSED!")
    print("=" * 60)
else:
    print("\n" + "=" * 60)
    print("✗ SOME TESTS FAILED")
    print("=" * 60)
