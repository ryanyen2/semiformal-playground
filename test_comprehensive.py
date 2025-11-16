"""
Comprehensive Test Suite for Mapping Analysis

Tests diverse scenarios to identify CORE issues:
1. Simple assignments
2. Complex NL phrases
3. Mixed Python + NL
4. Function definitions
5. Nested structures
6. Multiple references

Goal: Find generalizable patterns, not case-specific fixes
"""

import sys
import os
sys.path.insert(0, 'backend')

# Set API key if available
if len(sys.argv) > 1:
    os.environ['OPENAI_API_KEY'] = sys.argv[1]

from editor import BidirectionalEditor
from parser import parse_semiformal
from fine_grained_mapper import FineGrainedMapper
import json


TEST_CASES = [
    {
        'name': 'Simple assignment with NL',
        'code': 'x = load data from file',
    },
    {
        'name': 'Multiple NL operations',
        'code': '''data = load csv file
clean = remove missing values from data
result = normalize clean''',
    },
    {
        'name': 'Function call with args',
        'code': '''def process(x, y):
    return x + y

result = process(a, b)
print(result)''',
    },
    {
        'name': 'Mixed Python and NL',
        'code': '''import pandas as pd
df = load dataset
df = df.dropna()
print(df.head())''',
    },
    {
        'name': 'Hole with Python',
        'code': '''x = {compute something}
y = x * 2
print(x, y)''',
    },
    {
        'name': 'Complex NL with multiple verbs',
        'code': 'result = load data, clean it, and transform to features',
    },
    {
        'name': 'Reference same variable multiple times',
        'code': '''x = 10
y = x + 5
z = x * 2
print(x, y, z)''',
    },
]


def analyze_test_case(test_case, use_llm=False):
    """
    Test a single case and analyze results.

    Returns dict with analysis
    """
    name = test_case['name']
    semiformal_code = test_case['code']

    print("\n" + "="*80)
    print(f"TEST: {name}")
    print("="*80)
    print(f"Semiformal code:")
    for i, line in enumerate(semiformal_code.split('\n'), 1):
        print(f"  {i}: {line}")

    # Parse
    nodes = parse_semiformal(semiformal_code)
    print(f"\nParsed {len(nodes)} intent nodes:")
    for i, node in enumerate(nodes):
        print(f"  Node {i:2}: {node.type:15} '{node.content[:40]:40}' line={node.span[0]}")

    # Generate code (with or without LLM)
    if use_llm and os.environ.get('OPENAI_API_KEY'):
        print(f"\nGenerating with LLM...")
        editor = BidirectionalEditor()
        try:
            state = editor.initialize(semiformal_code)
            generated_code = state['python_code']
            print(f"Generated {len(generated_code.split(chr(10)))} lines")
        except Exception as e:
            print(f"LLM generation failed: {e}")
            generated_code = None
    else:
        print(f"\nSkipping LLM generation (no API key or disabled)")
        generated_code = None

    if generated_code:
        print(f"\nGenerated code:")
        for i, line in enumerate(generated_code.split('\n'), 1):
            print(f"  {i:2}: {line}")

        # Create fine-grained mappings
        mapper = FineGrainedMapper(generated_code)
        mappings = mapper.map_all_nodes(nodes)

        print(f"\nFine-grained mappings ({len(mappings)} total):")
        for mapping in mappings:
            intent_node = next((n for n in nodes if n.id == mapping.node_id), None)
            if intent_node:
                print(f"  {intent_node.type:15} '{intent_node.content[:30]:30}' → "
                      f"line {mapping.line:2} col {mapping.col_start:2}-{mapping.col_end:2} "
                      f"'{mapping.code_text[:40]:40}' ({mapping.mapping_type})")

        # Analysis
        analysis = analyze_mappings(nodes, mappings, generated_code)
        return analysis
    else:
        # No generated code, just analyze parsing
        analysis = {
            'name': name,
            'parsed_nodes': len(nodes),
            'generated': False,
            'issues': [],
        }

        # Analyze parsing quality
        nl_nodes = [n for n in nodes if n.type == 'nl_phrase']
        if nl_nodes:
            analysis['nl_phrase_count'] = len(nl_nodes)
            analysis['nl_phrases'] = [n.content for n in nl_nodes]

        return analysis


def analyze_mappings(nodes, mappings, generated_code):
    """
    Analyze mapping quality and identify issues.

    Returns dict with issues found
    """
    issues = []

    # Check 1: Are all nodes mapped?
    mapped_ids = {m.node_id for m in mappings}
    unmapped = [n for n in nodes if n.id not in mapped_ids]
    if unmapped:
        issues.append({
            'type': 'unmapped_nodes',
            'count': len(unmapped),
            'nodes': [{'type': n.type, 'content': n.content} for n in unmapped]
        })

    # Check 2: Do NL phrases map to different code?
    nl_mappings = {}
    for mapping in mappings:
        node = next((n for n in nodes if n.id == mapping.node_id), None)
        if node and node.type == 'nl_phrase':
            key = f"{mapping.line}:{mapping.col_start}-{mapping.col_end}"
            if key not in nl_mappings:
                nl_mappings[key] = []
            nl_mappings[key].append(node.content)

    for location, phrases in nl_mappings.items():
        if len(phrases) > 1:
            issues.append({
                'type': 'nl_phrases_same_location',
                'location': location,
                'phrases': phrases,
                'severity': 'high'
            })

    # Check 3: Do references map to correct usage (not definition)?
    for mapping in mappings:
        node = next((n for n in nodes if n.id == mapping.node_id), None)
        if node and node.type == 'identifier' and node.metadata.get('role') == 'reference':
            # Check if this maps to an assignment (Store context)
            # Should map to Load context
            if mapping.code_text and '=' in generated_code.split('\n')[mapping.line - 1]:
                # Might be mapping to assignment instead of reference
                line_content = generated_code.split('\n')[mapping.line - 1]
                if line_content.strip().startswith(node.content + ' ='):
                    issues.append({
                        'type': 'reference_maps_to_definition',
                        'node': node.content,
                        'line': mapping.line,
                        'severity': 'medium'
                    })

    # Check 4: Are identifiers mapping to specific tokens (not whole lines)?
    for mapping in mappings:
        node = next((n for n in nodes if n.id == mapping.node_id), None)
        if node and node.type == 'identifier':
            # Should have precise column mapping
            if mapping.col_end - mapping.col_start > len(node.content) + 10:
                # Mapping is too wide (might be entire line)
                issues.append({
                    'type': 'mapping_too_wide',
                    'node': node.content,
                    'width': mapping.col_end - mapping.col_start,
                    'expected': len(node.content),
                    'severity': 'low'
                })

    # Check 5: Duplicate code detection
    code_lines = generated_code.split('\n')
    seen_lines = {}
    for i, line in enumerate(code_lines, 1):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            if stripped not in seen_lines:
                seen_lines[stripped] = []
            seen_lines[stripped].append(i)

    duplicates = {line: lines for line, lines in seen_lines.items() if len(lines) > 1}
    if duplicates:
        issues.append({
            'type': 'duplicate_code',
            'count': len(duplicates),
            'examples': list(duplicates.items())[:3],
            'severity': 'high'
        })

    return {
        'total_nodes': len(nodes),
        'mapped_nodes': len(mappings),
        'coverage': len(mappings) / len(nodes) if nodes else 0,
        'issues': issues,
    }


def print_issue_summary(all_results):
    """Print summary of issues across all test cases"""

    print("\n" + "="*80)
    print("ISSUE SUMMARY ACROSS ALL TESTS")
    print("="*80)

    # Categorize issues
    issue_types = {}
    for result in all_results:
        if 'issues' in result:
            for issue in result['issues']:
                itype = issue['type']
                if itype not in issue_types:
                    issue_types[itype] = []
                issue_types[itype].append({
                    'test': result.get('name', 'unknown'),
                    'details': issue
                })

    print(f"\nFound {len(issue_types)} distinct issue types:\n")

    for itype, occurrences in sorted(issue_types.items()):
        print(f"\n{'='*60}")
        print(f"ISSUE: {itype}")
        print(f"{'='*60}")
        print(f"Occurrences: {len(occurrences)}")

        for occ in occurrences[:3]:  # Show first 3 examples
            print(f"\n  Test: {occ['test']}")
            details = occ['details']
            severity = details.get('severity', 'unknown')
            print(f"  Severity: {severity}")
            for key, value in details.items():
                if key not in ('type', 'severity'):
                    if isinstance(value, list) and len(value) > 3:
                        print(f"    {key}: {value[:3]} ... ({len(value)} total)")
                    else:
                        print(f"    {key}: {value}")

    # Core issue analysis
    print("\n" + "="*80)
    print("CORE ISSUES IDENTIFIED")
    print("="*80)

    # Analyze patterns
    if 'nl_phrases_same_location' in issue_types:
        print("\n1. NL PHRASE GRANULARITY PROBLEM")
        print("   Multiple NL phrases mapping to same location")
        print("   ROOT CAUSE: Semantic matching not granular enough")
        print("   SOLUTION NEEDED: Better phrase-to-code-fragment mapping")

    if 'unmapped_nodes' in issue_types:
        print("\n2. INCOMPLETE MAPPING")
        print("   Some nodes not mapped at all")
        print("   ROOT CAUSE: Mapper doesn't handle all node types")
        print("   SOLUTION NEEDED: Fallback mapping for all node types")

    if 'duplicate_code' in issue_types:
        print("\n3. CODE GENERATION QUALITY")
        print("   LLM generating duplicate code")
        print("   ROOT CAUSE: LLM prompt doesn't prevent duplication")
        print("   SOLUTION NEEDED: Post-processing deduplication + better prompts")

    if 'reference_maps_to_definition' in issue_types:
        print("\n4. DEFINITION vs REFERENCE CONFUSION")
        print("   References mapping to definitions")
        print("   ROOT CAUSE: Not checking AST context (Load vs Store)")
        print("   SOLUTION NEEDED: Better AST context checking")


def main():
    use_llm = os.environ.get('OPENAI_API_KEY') is not None

    if use_llm:
        print("="*80)
        print("RUNNING WITH LLM GENERATION")
        print("="*80)
    else:
        print("="*80)
        print("RUNNING WITHOUT LLM (parsing analysis only)")
        print("To test with LLM: OPENAI_API_KEY=your-key python test_comprehensive.py")
        print("="*80)

    all_results = []

    for test_case in TEST_CASES:
        result = analyze_test_case(test_case, use_llm=use_llm)
        result['name'] = test_case['name']
        all_results.append(result)

    # Print summary
    print_issue_summary(all_results)

    # Save results
    with open('test_results.json', 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\n\nDetailed results saved to test_results.json")


if __name__ == "__main__":
    main()
