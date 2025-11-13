"""
MVP Bidirectional Editor

Main orchestrator that ties together:
- Parser (intent nodes)
- Generator (code generation + mapping)
- Translator (edit translation)
- Direct operations (AST manipulation)
"""

from typing import List, Dict, Any, Optional
from mvp_parser import SemiformalParser, IntentNode, parse_semiformal
from mvp_generator import CodeGenerator, Mapping
from mvp_translator import EditTranslator, Edit, UpdateDecider
from mvp_edit import EditResult
from mvp_config import MVPConfig, DEFAULT_CONFIG


class BidirectionalEditor:
    """
    Main editor orchestrating semiformal ↔ Python synchronization.

    Implements Phases 1-3:
    - Phase 1: Direct AST edits
    - Phase 2: Placeholder support
    - Phase 3: Hole syntax and LLM generation
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        config: Optional[MVPConfig] = None
    ):
        """
        Initialize the bidirectional editor.

        Args:
            openai_api_key: OpenAI API key for LLM features
            config: Configuration object (uses DEFAULT_CONFIG if None)
        """
        self.config = config or DEFAULT_CONFIG
        self.parser = SemiformalParser()
        self.generator = CodeGenerator(openai_api_key, self.config)
        self.translator: Optional[EditTranslator] = None
        self.update_decider = UpdateDecider(self.config)

        # State
        self.semiformal_code = ""
        self.python_code = ""
        self.intent_nodes: List[IntentNode] = []
        self.mappings: List[Mapping] = []

    def initialize(self, semiformal_code: str) -> Dict[str, Any]:
        """
        Initialize from semiformal code.

        Flow:
        1. Parse semiformal → intent nodes
        2. Generate Python from nodes
        3. Create node→code mappings
        4. Set up translator

        Args:
            semiformal_code: The semiformal Python code

        Returns:
            Dict with python_code, nodes, and mappings
        """
        self.semiformal_code = semiformal_code

        # Step 1: Parse
        self.intent_nodes = self.parser.parse(semiformal_code)

        # Step 2: Generate Python
        self.python_code, self.mappings = self.generator.generate_with_mapping(
            self.intent_nodes,
            context=semiformal_code
        )

        # Step 3: Set up translator
        self.translator = EditTranslator(self.mappings, self.generator, self.config)

        return {
            'python_code': self.python_code,
            'nodes': [self._node_to_dict(node) for node in self.intent_nodes],
            'mappings': [self._mapping_to_dict(mapping) for mapping in self.mappings],
            'message': f'Parsed {len(self.intent_nodes)} intent nodes, generated {len(self.python_code.splitlines())} lines'
        }

    def on_semiformal_edit(self, edit: Edit) -> Dict[str, Any]:
        """
        Handle edit to semiformal code.

        Flow:
        1. Translate semiformal edit → Python edit
        2. Apply Python edit
        3. Update mappings if needed

        Args:
            edit: The edit made to semiformal code

        Returns:
            Dict with updated python_code and result info
        """
        if not self.translator:
            return {
                'success': False,
                'message': 'Editor not initialized. Call initialize() first.'
            }

        # Translate to Python edit
        result: EditResult = self.translator.semiformal_to_python(
            edit,
            self.semiformal_code,
            self.python_code
        )

        if result.success:
            # Apply the edit
            self.python_code = result.new_code

            # Update mappings if needed
            if result.needs_regeneration:
                self._handle_regeneration(result.regeneration_targets)

        return {
            'success': result.success,
            'python_code': self.python_code,
            'message': result.message,
            'needs_regeneration': result.needs_regeneration,
            'regeneration_targets': result.regeneration_targets
        }

    def on_python_edit(self, edit: Edit) -> Dict[str, Any]:
        """
        Handle edit to generated Python code.

        Flow:
        1. Apply the Python edit directly (no LLM needed for direct edits)
        2. Decide if should propagate (using UpdateDecider)
        3. If transient: just update Python
        4. If semantic: suggest semiformal update (only use LLM if needed)

        Args:
            edit: The edit made to Python code

        Returns:
            Dict with result info and optional semiformal suggestion
        """
        # First, try to apply the edit directly if it's a direct edit type
        # This avoids unnecessary LLM calls for simple edits
        if self.translator and self.translator._is_direct_translatable(edit):
            # Apply direct edit without LLM
            result = self.translator._direct_translate(edit, self.python_code)
            if result.success:
                self.python_code = result.new_code
                
                # Decide if should propagate
                should_propagate, strategy = self.update_decider.should_propagate(edit)
                
                return {
                    'success': True,
                    'propagate': should_propagate,
                    'message': result.message,
                    'python_code': self.python_code,
                    'strategy': strategy if should_propagate else 'none'
                }
        
        # For non-direct edits or if direct translation failed,
        # check if we can apply it as a simple text replacement
        # (e.g., user typed new content directly)
        if edit.content and edit.line is not None:
            # Simple line replacement - apply directly
            lines = self.python_code.split('\n')
            if 0 <= edit.line < len(lines):
                lines[edit.line] = edit.content
                self.python_code = '\n'.join(lines)
                
                # Decide if should propagate
                should_propagate, strategy = self.update_decider.should_propagate(edit)
                
                return {
                    'success': True,
                    'propagate': should_propagate,
                    'message': f'Applied Python edit directly on line {edit.line}',
                    'python_code': self.python_code,
                    'strategy': strategy if should_propagate else 'none'
                }
        
        # Decide if should propagate
        should_propagate, strategy = self.update_decider.should_propagate(edit)

        if not should_propagate:
            # Transient change - just note it
            return {
                'success': True,
                'propagate': False,
                'message': 'Transient edit - not propagating to semiformal',
                'edit_type': edit.type,
                'python_code': self.python_code
            }

        # Semantic change - should propagate
        # Only use LLM for generating suggestions if it's a complex semantic change
        # For simple changes, just provide a basic suggestion
        if strategy == 'llm' and self.generator.client:
            suggestion = self._generate_semiformal_suggestion(edit)
        else:
            # Simple suggestion without LLM
            suggestion = f"# Suggested: {edit.type} - {edit.content}"

        return {
            'success': True,
            'propagate': True,
            'message': f'Semantic change detected - suggest updating semiformal',
            'suggestion': suggestion,
            'strategy': strategy,
            'python_code': self.python_code
        }

    def apply_direct_edit(
        self,
        edit_type: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Apply a direct edit operation.

        Convenience method for common direct edits.

        Args:
            edit_type: Type of edit (rename, add_param, etc.)
            **kwargs: Edit-specific arguments

        Returns:
            Dict with result info
        """
        edit = Edit(
            type=edit_type,
            location=kwargs.get('location', ''),
            content=kwargs.get('content', ''),
            old_content=kwargs.get('old_content'),
            line=kwargs.get('line'),
            metadata=kwargs.get('metadata', {})
        )

        return self.on_semiformal_edit(edit)

    def fill_hole(
        self,
        line_num: int,
        hint: str = "",
        target_var: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fill a hole on a specific line.

        Phase 3: Hole filling

        Args:
            line_num: Line number with the hole
            hint: Optional hint for LLM
            target_var: Variable being assigned to

        Returns:
            Dict with filled code
        """
        edit = Edit(
            type='hole_fill',
            location=str(line_num),
            content=hint,
            line=line_num,
            metadata={'target_var': target_var}
        )

        if not self.translator:
            return {
                'success': False,
                'message': 'Editor not initialized'
            }

        result = self.translator.semiformal_to_python(
            edit,
            self.semiformal_code,
            self.python_code
        )

        if result.success:
            self.python_code = result.new_code

        return {
            'success': result.success,
            'python_code': self.python_code,
            'message': result.message
        }

    def regenerate(self, target: Optional[str] = None) -> Dict[str, Any]:
        """
        Regenerate code for a specific target or entire code.

        Args:
            target: Optional function name or section to regenerate

        Returns:
            Dict with regenerated code
        """
        # Re-parse semiformal code
        self.intent_nodes = self.parser.parse(self.semiformal_code)

        # Re-generate Python
        self.python_code, self.mappings = self.generator.generate_with_mapping(
            self.intent_nodes,
            context=self.semiformal_code
        )

        # Update translator
        self.translator = EditTranslator(self.mappings, self.generator, self.config)

        return {
            'success': True,
            'python_code': self.python_code,
            'message': f'Regenerated {"entire code" if not target else target}'
        }

    def get_state(self) -> Dict[str, Any]:
        """
        Get current editor state.

        Returns:
            Dict with all current state information
        """
        return {
            'semiformal_code': self.semiformal_code,
            'python_code': self.python_code,
            'nodes': [self._node_to_dict(node) for node in self.intent_nodes],
            'mappings': [self._mapping_to_dict(mapping) for mapping in self.mappings],
            'has_llm': self.generator.client is not None
        }

    def _handle_regeneration(self, targets: List[str]):
        """Handle regeneration of specific targets"""
        # For now, regenerate entire code
        # Production would regenerate only affected sections
        if targets:
            print(f"Regeneration needed for: {', '.join(targets)}")
            # TODO: Implement targeted regeneration

    def _generate_semiformal_suggestion(self, edit: Edit) -> str:
        """
        Generate a suggestion for updating semiformal code.

        Uses LLM to summarize Python change in natural language.
        """
        if not self.generator.client:
            return f"# TODO: Update semiformal for edit: {edit.type}"

        # For now, simple suggestion
        return f"# Suggested: {edit.type} - {edit.content}"

    def _node_to_dict(self, node: IntentNode) -> Dict[str, Any]:
        """Convert IntentNode to dict for JSON serialization"""
        # Extract line number from span
        line = node.span[0] + 1  # Convert to 1-based line number
        
        # Extract column by finding where content appears in the line
        col = 0
        if self.semiformal_code:
            lines = self.semiformal_code.split('\n')
            if line - 1 < len(lines):
                line_text = lines[line - 1]
                # Find the position of the content in the line
                content_pos = line_text.find(node.content)
                if content_pos >= 0:
                    col = content_pos
                else:
                    # If content not found, try to find similar content
                    # For now, default to 0
                    col = 0
        
        return {
            'type': node.type,
            'value': node.content,
            'line': line,
            'col': col,
            'metadata': node.metadata
        }

    def _mapping_to_dict(self, mapping: Mapping) -> Dict[str, Any]:
        """Convert Mapping to dict for JSON serialization"""
        # Find node index from node_id
        node_index = -1
        for i, node in enumerate(self.intent_nodes):
            if node.id == mapping.node_id:
                node_index = i
                break
        
        # Extract code information from first slice
        code_line = 0
        code_col = 0
        code_snippet = ""
        if mapping.slices:
            first_slice = mapping.slices[0]
            code_line = first_slice.line_start  # Already 1-based from AST
            code_snippet = first_slice.code
            
            # Try to get column from AST nodes if available
            if first_slice.ast_nodes:
                ast_node = first_slice.ast_nodes[0]
                if hasattr(ast_node, 'col_offset'):
                    code_col = ast_node.col_offset
                else:
                    code_col = 0
            else:
                code_col = 0
        
        return {
            'node_index': node_index,
            'code_line': code_line,
            'code_col': code_col,
            'code_snippet': code_snippet
        }


# Convenience functions for common operations

def create_editor(openai_api_key: Optional[str] = None) -> BidirectionalEditor:
    """Create and return a new BidirectionalEditor instance"""
    return BidirectionalEditor(openai_api_key)


def parse_and_generate(
    semiformal_code: str,
    openai_api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    One-shot parse and generate from semiformal code.

    Args:
        semiformal_code: The semiformal Python code
        openai_api_key: Optional OpenAI API key

    Returns:
        Dict with python_code and metadata
    """
    editor = BidirectionalEditor(openai_api_key)
    return editor.initialize(semiformal_code)
