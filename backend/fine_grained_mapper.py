"""
Fine-Grained AST Mapping

Maps IRNodes to specific AST nodes with column-level precision.
Handles NL phrases by mapping to their corresponding code fragments.
"""

import ast
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from ir import IRNode, NodeType, SourceLocation, ProgramIR


@dataclass
class ASTMapping:
    """Fine-grained mapping to specific AST node"""
    node_id: str
    ast_node: ast.AST
    line: int
    col_start: int
    col_end: int
    code_text: str
    confidence: float
    mapping_type: str  # 'exact', 'semantic', 'inferred'


class FineGrainedMapper:
    """Maps IRNodes to specific AST nodes (not entire lines)"""

    def __init__(self, generated_code: str):
        self.code = generated_code
        self.code_lines = generated_code.split('\n')
        try:
            self.ast_tree = ast.parse(generated_code)
        except SyntaxError:
            self.ast_tree = None

        # Build indices
        self.name_nodes: List[Tuple[ast.Name, int, int, int]] = []
        self.call_nodes: List[Tuple[ast.Call, int, int, int]] = []
        self.assign_nodes: List[Tuple[ast.Assign, int]] = []
        self.function_def_nodes: List[Tuple[ast.FunctionDef, int]] = []
        self.import_nodes: List[Tuple[ast.AST, int]] = []
        self.constant_nodes: List[Tuple[ast.Constant, int, int, int]] = []
        self.binop_nodes: List[Tuple[ast.BinOp, int, int, int]] = []

        if self.ast_tree:
            self._build_indices()

    def _build_indices(self):
        """Build indices of all AST nodes"""
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.Name):
                line = getattr(node, 'lineno', 0)
                col_start = getattr(node, 'col_offset', 0)
                col_end = getattr(node, 'end_col_offset', col_start + len(node.id))
                self.name_nodes.append((node, line, col_start, col_end))

            elif isinstance(node, ast.Call):
                line = getattr(node, 'lineno', 0)
                col_start = getattr(node, 'col_offset', 0)
                col_end = getattr(node, 'end_col_offset', col_start)
                self.call_nodes.append((node, line, col_start, col_end))

            elif isinstance(node, ast.Assign):
                line = getattr(node, 'lineno', 0)
                self.assign_nodes.append((node, line))

            elif isinstance(node, ast.FunctionDef):
                line = getattr(node, 'lineno', 0)
                self.function_def_nodes.append((node, line))

            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                line = getattr(node, 'lineno', 0)
                self.import_nodes.append((node, line))

            elif isinstance(node, ast.Constant):
                line = getattr(node, 'lineno', 0)
                col_start = getattr(node, 'col_offset', 0)
                col_end = getattr(node, 'end_col_offset', col_start)
                self.constant_nodes.append((node, line, col_start, col_end))

            elif isinstance(node, ast.BinOp):
                line = getattr(node, 'lineno', 0)
                col_start = getattr(node, 'col_offset', 0)
                col_end = getattr(node, 'end_col_offset', col_start)
                self.binop_nodes.append((node, line, col_start, col_end))

    def map_node(
        self,
        ir_node: IRNode,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """
        Map an IRNode to AST node based on its type.
        """
        if ir_node.node_type == NodeType.VARIABLE_ASSIGN:
            return self.map_assignment(ir_node, expected_line)
        elif ir_node.node_type == NodeType.VARIABLE_REF:
            return self.map_identifier(ir_node, expected_line)
        elif ir_node.node_type == NodeType.FUNCTION_CALL:
            return self.map_function_call(ir_node, expected_line)
        elif ir_node.node_type == NodeType.FUNCTION_DEF:
            return self.map_function_def(ir_node, expected_line)
        elif ir_node.node_type == NodeType.NL_EXPRESSION:
            return self.map_nl_expression(ir_node, expected_line)

        return None

    def map_assignment(
        self,
        ir_node: IRNode,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map variable assignment to AST Assign node"""
        name = ir_node.name

        # Find assignment where this is the target
        for assign_node, line in self.assign_nodes:
            for target in assign_node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    col_start = getattr(target, 'col_offset', 0)
                    col_end = getattr(target, 'end_col_offset', col_start + len(name))
                    code_text = self._extract_text(line, col_start, col_end)

                    return ASTMapping(
                        node_id=ir_node.id,
                        ast_node=target,
                        line=line,
                        col_start=col_start,
                        col_end=col_end,
                        code_text=code_text,
                        confidence=0.95,
                        mapping_type='exact'
                    )

                # Handle tuple unpacking: x, y = ...
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name) and elt.id == name:
                            col_start = getattr(elt, 'col_offset', 0)
                            col_end = getattr(elt, 'end_col_offset', col_start + len(name))
                            code_text = self._extract_text(line, col_start, col_end)

                            return ASTMapping(
                                node_id=ir_node.id,
                                ast_node=elt,
                                line=line,
                                col_start=col_start,
                                col_end=col_end,
                                code_text=code_text,
                                confidence=0.95,
                                mapping_type='exact'
                            )

        return None

    def map_identifier(
        self,
        ir_node: IRNode,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map identifier reference to Name AST node"""
        name = ir_node.name

        candidates = []
        for name_node, line, col_start, col_end in self.name_nodes:
            if name_node.id == name and isinstance(name_node.ctx, ast.Load):
                score = 100

                # Prefer matches closer to expected line
                if expected_line:
                    distance = abs(line - expected_line)
                    score -= distance * 20

                candidates.append((score, name_node, line, col_start, col_end))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, name_node, line, col_start, col_end = candidates[0]

            code_text = self._extract_text(line, col_start, col_end)

            return ASTMapping(
                node_id=ir_node.id,
                ast_node=name_node,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.9,
                mapping_type='exact'
            )

        return None

    def map_function_call(
        self,
        ir_node: IRNode,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map function call to specific Call AST node"""
        func_name = ir_node.name

        candidates = []
        for call_node, line, col_start, col_end in self.call_nodes:
            # Check if this call matches the function name
            if isinstance(call_node.func, ast.Name) and call_node.func.id == func_name:
                score = 100

                # Prefer matches closer to expected line
                if expected_line:
                    distance = abs(line - expected_line)
                    score -= distance

                candidates.append((score, call_node, line, col_start, col_end))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, call_node, line, col_start, col_end = candidates[0]

            code_text = self._extract_text(line, col_start, col_end)

            return ASTMapping(
                node_id=ir_node.id,
                ast_node=call_node,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.9,
                mapping_type='exact'
            )

        return None

    def map_function_def(
        self,
        ir_node: IRNode,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """Map function definition to FunctionDef AST node"""
        func_name = ir_node.name

        candidates = []
        for func_def, line in self.function_def_nodes:
            if func_def.name == func_name:
                score = 100

                # Prefer matches closer to expected line
                if expected_line:
                    distance = abs(line - expected_line)
                    score -= distance * 10

                candidates.append((score, func_def, line))

        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            _, func_def, line = candidates[0]

            # Map to function name (not entire def)
            col_start = getattr(func_def, 'col_offset', 0) + 4  # After 'def '
            col_end = col_start + len(func_name)
            code_text = self._extract_text(line, col_start, col_end)

            return ASTMapping(
                node_id=ir_node.id,
                ast_node=func_def,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.95,
                mapping_type='exact'
            )

        return None

    def map_nl_expression(
        self,
        ir_node: IRNode,
        expected_line: Optional[int] = None
    ) -> Optional[ASTMapping]:
        """
        Map NL expression to generated code.

        For NL expressions, we look at the RHS metadata to understand
        what code was generated for it.
        """
        nl_text = ir_node.metadata.get('rhs', '').lower()

        # Analyze NL phrase meaning
        if 'load' in nl_text or 'read' in nl_text:
            # Find read_csv or similar loading call
            for call_node, line, col_start, col_end in self.call_nodes:
                if isinstance(call_node.func, ast.Attribute):
                    if call_node.func.attr in ('read_csv', 'read_excel', 'load'):
                        code_text = self._extract_text(line, col_start, col_end)
                        return ASTMapping(
                            node_id=ir_node.id,
                            ast_node=call_node,
                            line=line,
                            col_start=col_start,
                            col_end=col_end,
                            code_text=code_text,
                            confidence=0.75,
                            mapping_type='semantic'
                        )

        # Fallback: use code_location if available
        if ir_node.code_location:
            line = ir_node.code_location.line
            col_start = ir_node.code_location.col
            col_end = ir_node.code_location.end_col or col_start

            code_text = self._extract_text(line, col_start, col_end)

            return ASTMapping(
                node_id=ir_node.id,
                ast_node=None,
                line=line,
                col_start=col_start,
                col_end=col_end,
                code_text=code_text,
                confidence=0.8,
                mapping_type='exact'
            )

        return None

    def _extract_text(self, line: int, col_start: int, col_end: int) -> str:
        """Extract text from code at specific position"""
        if 1 <= line <= len(self.code_lines):
            line_text = self.code_lines[line - 1]
            if col_end <= len(line_text):
                return line_text[col_start:col_end]
        return ""

    def map_all_nodes(self, ir: ProgramIR) -> Dict[str, ASTMapping]:
        """
        Map all IR nodes to AST nodes.

        Returns a dictionary mapping node IDs to ASTMapping.
        """
        mappings = {}

        for node_id, ir_node in ir.nodes.items():
            # Get expected line from spec location
            expected_line = None
            if ir_node.spec_location:
                expected_line = ir_node.spec_location.line

            # Map the node
            mapping = self.map_node(ir_node, expected_line)
            if mapping:
                mappings[node_id] = mapping

        return mappings
