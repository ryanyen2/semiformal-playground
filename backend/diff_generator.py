"""
Unified-diff based code generator.

This generator analyzes the whole program and produces unified-diff format
output instead of assembling code slice by slice. It maintains proper mapping
to the IR for robust bidirectional synchronization.

Key features:
- Program-wide context analysis
- Unified-diff format (headers, hunks, context lines)
- Dependency-aware generation order
- Direct IR integration
"""

import os
import difflib
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from openai import OpenAI
from dotenv import load_dotenv

from ir import ProgramIR, IRNode, NodeType, NodeStatus
from skeleton_generator import generate_skeleton

load_dotenv()


@dataclass
class DiffHunk:
    """Represents a hunk in a unified diff."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[str]  # Diff lines with +/- prefixes
    context_before: List[str]
    context_after: List[str]


@dataclass
class UnifiedDiff:
    """Complete unified diff for code changes."""
    old_file: str
    new_file: str
    hunks: List[DiffHunk]
    
    def to_string(self) -> str:
        """Convert to unified diff format string."""
        lines = []
        lines.append(f"--- {self.old_file}")
        lines.append(f"+++ {self.new_file}")
        
        for hunk in self.hunks:
            # Hunk header
            lines.append(
                f"@@ -{hunk.old_start},{hunk.old_count} "
                f"+{hunk.new_start},{hunk.new_count} @@"
            )
            
            # Context before
            for line in hunk.context_before:
                lines.append(f" {line}")
            
            # Changes
            for line in hunk.lines:
                lines.append(line)
            
            # Context after
            for line in hunk.context_after:
                lines.append(f" {line}")
        
        return "\n".join(lines)


class DiffGenerator:
    """
    Generates code using LLM with program-wide context.
    
    Instead of generating slice by slice, this analyzes the entire program
    and generates complete, coherent implementations.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the diff generator."""
        self.client = OpenAI(api_key=api_key or os.getenv('OPENAI_API_KEY'))
        self.model = "gpt-4o"
    
    def generate_from_ir(self, ir: ProgramIR) -> Tuple[str, List[UnifiedDiff]]:
        """
        Generate complete code from IR.
        
        First generates skeleton (preserving already-generated code),
        then uses LLM only for truly incomplete nodes.
        
        Args:
            ir: ProgramIR with incomplete nodes marked
        
        Returns:
            Tuple of (generated_code, list_of_diffs)
        """
        # First, generate skeleton which preserves already-generated code
        skeleton_code = generate_skeleton(ir)
        
        # Get nodes that need LLM generation (INCOMPLETE or NEEDS_REGEN)
        incomplete_nodes = ir.get_incomplete_nodes()
        
        if not incomplete_nodes:
            # No generation needed, return skeleton
            ir.code_source = skeleton_code
            diffs = self._create_diffs(ir.spec_source, skeleton_code)
            return skeleton_code, diffs
        
        # Sort nodes by dependency order (topological)
        ordered_node_ids = ir.topological_sort()
        ordered_incomplete = [
            node for nid in ordered_node_ids
            for node in incomplete_nodes
            if node.id == nid
        ]
        
        # Build complete program context
        context = self._build_program_context(ir)
        context['skeleton_code'] = skeleton_code  # Include skeleton in context
        
        # Generate implementations for all incomplete nodes at once
        implementations = self._generate_implementations(
            ordered_incomplete,
            context,
            ir
        )
        
        # Apply implementations to skeleton (not spec!)
        generated_code = self._apply_implementations(
            skeleton_code,
            implementations,
            ir
        )
        
        # Generate diffs from skeleton to final code
        diffs = self._create_diffs(skeleton_code, generated_code)
        
        # Update IR with generated code and locations
        code_lines = generated_code.split('\n')
        for node in incomplete_nodes:
            if node.id in implementations:
                node.code_text = implementations[node.id]
                # Update status: NEEDS_REGEN -> GENERATED, INCOMPLETE -> GENERATED
                node.status = NodeStatus.GENERATED
                
                # Update code location for bidirectional mapping
                # Find the line where this node's code appears
                impl_lines = implementations[node.id].split('\n')
                for i, line in enumerate(code_lines):
                    if impl_lines[0] in line:
                        from ir import SourceLocation
                        node.code_location = SourceLocation(
                            line=i + 1,
                            col=0,
                            end_line=i + len(impl_lines),
                            end_col=len(impl_lines[-1]) if impl_lines else 0
                        )
                        break
        
        ir.code_source = generated_code
        
        return generated_code, diffs
    
    def _build_program_context(self, ir: ProgramIR) -> Dict[str, Any]:
        """
        Build complete program context for generation.
        
        This includes:
        - All defined functions and variables
        - Dependencies between elements
        - Type hints and annotations
        - Natural language specifications
        - Already-generated code for context
        """
        context = {
            'spec_source': ir.spec_source,
            'functions': {},
            'variables': {},
            'nl_descriptions': {},
            'dependencies': {},
            'complete_elements': [],
            'generated_elements': []
        }
        
        for node_id, node in ir.nodes.items():
            if node.node_type == NodeType.FUNCTION_DEF:
                context['functions'][node.name] = {
                    'spec': node.spec_text,
                    'status': node.status.value,
                    'dependencies': list(node.depends_on),
                    'signature': node.spec_signature
                }
                
                if node.status == NodeStatus.SYNCED:
                    context['complete_elements'].append(node.spec_text)
                elif node.status in (NodeStatus.GENERATED, NodeStatus.USER_EDITED):
                    # Include already-generated code for context
                    if node.code_text:
                        context['generated_elements'].append(node.code_text)
            
            elif node.node_type in (NodeType.VARIABLE_ASSIGN, NodeType.NL_EXPRESSION):
                context['variables'][node.name] = {
                    'spec': node.spec_text,
                    'status': node.status.value,
                    'is_nl': node.metadata.get('is_nl', False)
                }
                
                if node.metadata.get('is_nl'):
                    rhs = node.metadata.get('rhs', '')
                    context['nl_descriptions'][node.name] = rhs
        
        # Add dependency information
        for node_id, deps in ir.dependency_graph.items():
            node = ir.nodes.get(node_id)
            if node:
                context['dependencies'][node.name] = [
                    ir.nodes[dep_id].name
                    for dep_id in deps
                    if dep_id in ir.nodes
                ]
        
        return context
    
    def _generate_implementations(
        self,
        incomplete_nodes: List[IRNode],
        context: Dict[str, Any],
        ir: ProgramIR
    ) -> Dict[str, str]:
        """
        Generate implementations for all incomplete nodes.
        
        Uses LLM with full program context to generate coherent,
        consistent implementations.
        """
        if not incomplete_nodes:
            return {}
        
        # Build prompt with complete context
        prompt = self._build_generation_prompt(incomplete_nodes, context)
        
        # Generate with LLM
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Python programmer. Generate complete, "
                        "working Python code from semiformal specifications. "
                        "CRITICAL: Add a descriptive comment BEFORE each statement as an anchor. "
                        "These comments help with code mapping and backward slicing. "
                        "Analyze the entire program context and generate coherent "
                        "implementations that respect dependencies. "
                        "Provide ONLY Python code without markdown formatting."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=3000
        )
        
        generated_code = response.choices[0].message.content.strip()
        
        # Parse generated code and extract implementations
        implementations = self._extract_implementations(
            generated_code,
            incomplete_nodes
        )
        
        return implementations
    
    def _build_generation_prompt(
        self,
        incomplete_nodes: List[IRNode],
        context: Dict[str, Any]
    ) -> str:
        """Build prompt for LLM generation with full context."""
        lines = []

        lines.append("Generate complete Python code from this semiformal specification:")
        lines.append("")
        lines.append("```python")
        lines.append(context['spec_source'])
        lines.append("```")
        lines.append("")

        lines.append("Elements that need implementation:")
        for node in incomplete_nodes:
            if node.node_type == NodeType.FUNCTION_DEF:
                lines.append(f"- Function '{node.name}': {node.spec_text.strip()}")

                deps = context['dependencies'].get(node.name, [])
                if deps:
                    lines.append(f"  Dependencies: {', '.join(deps)}")

            elif node.node_type == NodeType.NL_EXPRESSION:
                nl_desc = context['nl_descriptions'].get(node.name, '')
                lines.append(f"- Variable '{node.name}' = {nl_desc}")

            elif node.node_type == NodeType.FUNCTION_CALL:
                lines.append(f"- Undefined function '{node.name}' needs stub")

        lines.append("")
        lines.append("IMPORTANT: Generate complete Python code with the following requirements:")
        lines.append("1. Add a descriptive comment BEFORE each statement (assignment, function call, return, etc.)")
        lines.append("2. These comments serve as anchors for code mapping and should describe what the statement does")
        lines.append("3. Use concise, clear comments like '# load data', '# process results', '# return value'")
        lines.append("4. Maintain the structure and respect dependencies")
        lines.append("5. Replace '...' with actual implementations")
        lines.append("6. Convert natural language expressions to Python code")
        lines.append("")
        lines.append("Example format:")
        lines.append("```python")
        lines.append("def process_data(filename):")
        lines.append("    # load csv file")
        lines.append("    data = pd.read_csv(filename)")
        lines.append("    # clean missing values")
        lines.append("    cleaned = data.dropna()")
        lines.append("    # return cleaned data")
        lines.append("    return cleaned")
        lines.append("```")
        lines.append("")
        lines.append("Output the complete, executable Python program with statement comments:")

        return "\n".join(lines)
    
    def _extract_implementations(
        self,
        generated_code: str,
        incomplete_nodes: List[IRNode]
    ) -> Dict[str, str]:
        """
        Extract implementations for each node from generated code.
        
        Maps generated code back to IR nodes.
        """
        # Clean markdown fences
        generated_code = self._clean_code_fences(generated_code)
        
        implementations = {}
        lines = generated_code.split('\n')
        
        for node in incomplete_nodes:
            if node.node_type == NodeType.FUNCTION_DEF:
                # Extract function implementation
                impl = self._extract_function(lines, node.name)
                if impl:
                    implementations[node.id] = impl
            
            elif node.node_type in (NodeType.VARIABLE_ASSIGN, NodeType.NL_EXPRESSION):
                # Extract variable assignment
                impl = self._extract_assignment(lines, node.name)
                if impl:
                    implementations[node.id] = impl
            
            elif node.node_type == NodeType.FUNCTION_CALL:
                # Extract stub function
                impl = self._extract_function(lines, node.name)
                if impl:
                    implementations[node.id] = impl
        
        return implementations
    
    def _extract_function(self, lines: List[str], func_name: str) -> Optional[str]:
        """Extract function implementation from lines."""
        func_lines = []
        in_function = False
        indent_level = 0
        
        for line in lines:
            if f"def {func_name}(" in line:
                in_function = True
                indent_level = len(line) - len(line.lstrip())
                func_lines.append(line)
            elif in_function:
                if line.strip() and not line[0].isspace():
                    # End of function
                    break
                elif line.strip() and len(line) - len(line.lstrip()) <= indent_level:
                    # Dedent, end of function
                    break
                else:
                    func_lines.append(line)
        
        return '\n'.join(func_lines) if func_lines else None
    
    def _extract_assignment(self, lines: List[str], var_name: str) -> Optional[str]:
        """Extract variable assignment from lines."""
        for line in lines:
            if line.strip().startswith(f"{var_name} ="):
                return line.strip()
        return None
    
    def _apply_implementations(
        self,
        spec_source: str,
        implementations: Dict[str, str],
        ir: ProgramIR
    ) -> str:
        """
        Apply implementations to spec source.
        
        Replaces incomplete parts with generated implementations.
        """
        lines = spec_source.split('\n')
        result = []
        skip_until = -1
        
        for i, line in enumerate(lines):
            if i < skip_until:
                continue
            
            # Check if this line matches any node
            matched = False
            for node_id, impl in implementations.items():
                node = ir.nodes.get(node_id)
                if not node or not node.spec_location:
                    continue
                
                if node.spec_location.line == i + 1:
                    # Replace with implementation
                    result.append(impl)
                    
                    # Skip ellipsis line if present
                    if i + 1 < len(lines) and '...' in lines[i + 1]:
                        skip_until = i + 2
                    
                    matched = True
                    break
            
            if not matched:
                result.append(line)
        
        return '\n'.join(result)
    
    def _create_diffs(self, old_code: str, new_code: str) -> List[UnifiedDiff]:
        """
        Create unified diffs between old and new code.
        
        Returns proper diff format with hunks.
        """
        old_lines = old_code.split('\n')
        new_lines = new_code.split('\n')
        
        # Use difflib to generate diff
        differ = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile='spec.py',
            tofile='generated.py',
            lineterm=''
        )
        
        diff_lines = list(differ)
        
        # Parse diff into structured format
        hunks = self._parse_diff_hunks(diff_lines)
        
        if hunks:
            return [UnifiedDiff(
                old_file='spec.py',
                new_file='generated.py',
                hunks=hunks
            )]
        else:
            return []
    
    def _parse_diff_hunks(self, diff_lines: List[str]) -> List[DiffHunk]:
        """Parse unified diff lines into structured hunks."""
        hunks = []
        current_hunk = None
        
        for line in diff_lines:
            if line.startswith('@@'):
                # New hunk
                if current_hunk:
                    hunks.append(current_hunk)
                
                # Parse hunk header
                import re
                match = re.match(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', line)
                if match:
                    current_hunk = DiffHunk(
                        old_start=int(match.group(1)),
                        old_count=int(match.group(2)),
                        new_start=int(match.group(3)),
                        new_count=int(match.group(4)),
                        lines=[],
                        context_before=[],
                        context_after=[]
                    )
            
            elif line.startswith('---') or line.startswith('+++'):
                # File headers, skip
                continue
            
            elif current_hunk is not None:
                current_hunk.lines.append(line)
        
        if current_hunk:
            hunks.append(current_hunk)
        
        return hunks
    
    def _clean_code_fences(self, code: str) -> str:
        """Remove markdown code fences from generated code."""
        lines = code.split('\n')
        cleaned = []
        
        for line in lines:
            stripped = line.strip()
            if stripped in ('```', '```python', '```py'):
                continue
            cleaned.append(line)
        
        return '\n'.join(cleaned)


def generate_code_with_diffs(ir: ProgramIR) -> Tuple[str, List[UnifiedDiff]]:
    """
    Convenience function to generate code and diffs from IR.
    
    Args:
        ir: ProgramIR with incomplete nodes
    
    Returns:
        Tuple of (generated_code, diffs)
    """
    generator = DiffGenerator()
    return generator.generate_from_ir(ir)

