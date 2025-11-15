"""
Debug tree mapper to see what's happening with AST nodes
"""

import sys
import ast
sys.path.insert(0, 'backend')

from parser import parse_semiformal
from tree_mapper import TreeMapper, MappingAdapter


def debug_tree_mapping():
    semiformal_code = """result = load dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)"""

    # Generated code (simulating what generator produces without LLM)
    generated_code = """def transform(result):
    \"\"\"TODO: Implement this function.\"\"\"
    raise NotImplementedError("Function transform needs implementation")

result = None  # TODO: Fill this placeholder
output = transform(result)
x, y = None, None  # TODO: Fill these placeholders
print(output)"""

    print("="*80)
    print("SEMIFORMAL CODE:")
    print("="*80)
    print(semiformal_code)

    print("\n" + "="*80)
    print("GENERATED CODE:")
    print("="*80)
    for i, line in enumerate(generated_code.split('\n'), 1):
        print(f"{i:2}: {line}")

    # Parse semiformal
    nodes = parse_semiformal(semiformal_code)

    print("\n" + "="*80)
    print("INTENT NODES:")
    print("="*80)
    for i, node in enumerate(nodes):
        print(f"{i:2}: {node.type:15} '{node.content:20}' line={node.span[0]}")

    # Build trees
    mapper = TreeMapper()
    ir_tree = mapper.build_ir_tree(nodes)
    ast_tree = mapper.build_ast_tree(generated_code)

    print("\n" + "="*80)
    print("PYTHON AST TREE:")
    print("="*80)

    # Parse AST and show line numbers
    try:
        tree = ast.parse(generated_code)
        for node in ast.walk(tree):
            if hasattr(node, 'lineno'):
                node_type = node.__class__.__name__
                content = ""
                if isinstance(node, ast.Name):
                    content = node.id
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        content = f"{node.func.id}(...)"
                elif isinstance(node, ast.Expr):
                    content = "expr"
                elif isinstance(node, ast.Assign):
                    content = "assign"
                elif isinstance(node, ast.FunctionDef):
                    content = node.name

                if content:
                    print(f"  {node_type:20} line={node.lineno:2} end={getattr(node, 'end_lineno', '?'):2} {content}")
    except Exception as e:
        print(f"Error parsing AST: {e}")

    # Do tree mapping
    tree_mappings = mapper.map_trees(ir_tree, ast_tree)

    print("\n" + "="*80)
    print("TREE MAPPINGS:")
    print("="*80)
    for i, tm in enumerate(tree_mappings):
        ir_content = tm.ir_node.content if tm.ir_node else "?"
        ast_content = tm.ast_node.content if tm.ast_node else "None"
        ast_line = tm.ast_node.line if tm.ast_node else "?"
        mapping_type = tm.mapping_type.value

        print(f"{i:2}: IR='{ir_content:20}' → AST='{ast_content:20}' line={ast_line:2} type={mapping_type}")

        # Check if ast_node has source
        if tm.ast_node and tm.ast_node.source_node:
            src = tm.ast_node.source_node
            if isinstance(src, ast.AST):
                lineno = getattr(src, 'lineno', '?')
                end_lineno = getattr(src, 'end_lineno', '?')
                print(f"     AST source: {src.__class__.__name__} lineno={lineno} end_lineno={end_lineno}")

    # Convert to code mappings
    code_mappings = MappingAdapter.convert_tree_mappings_to_code_mappings(
        tree_mappings,
        generated_code
    )

    print("\n" + "="*80)
    print("CODE MAPPINGS (after conversion):")
    print("="*80)
    for i, mapping in enumerate(code_mappings):
        node_id = mapping.node_id
        # Find the intent node
        intent_node = next((n for n in nodes if n.id == node_id), None)
        if intent_node:
            if mapping.slices:
                slice0 = mapping.slices[0]
                print(f"{i:2}: Node '{intent_node.content:20}' (sf line {intent_node.span[0]}) → gen line {slice0.line_start} '{slice0.code}'")
            else:
                print(f"{i:2}: Node '{intent_node.content:20}' (sf line {intent_node.span[0]}) → NO SLICES")

    print("\n" + "="*80)
    print("CHECKING FOR ISSUES:")
    print("="*80)

    # Check for incorrect mappings
    for mapping in code_mappings:
        intent_node = next((n for n in nodes if n.id == mapping.node_id), None)
        if intent_node and mapping.slices:
            sf_line = intent_node.span[0]
            gen_line = mapping.slices[0].line_start
            code_snippet = mapping.slices[0].code

            # Check if the mapping makes sense
            # Semiformal line 7 should map to generated line 8 (print)
            if sf_line == 7 and intent_node.content == 'print(output)':
                if gen_line != 8:
                    print(f"❌ BUG: Semiformal line 7 'print(output)' maps to gen line {gen_line} instead of 8")
                    print(f"   Code: {code_snippet}")
                else:
                    print(f"✓ OK: Semiformal line 7 'print(output)' correctly maps to gen line 8")


if __name__ == "__main__":
    debug_tree_mapping()
