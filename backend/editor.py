"""
MVP Bidirectional Editor

Main orchestrator that ties together:
- Parser (intent nodes)
- Generator (code generation + mapping)
- Translator (edit translation)
- Direct operations (AST manipulation)
"""

from typing import List, Dict, Any, Optional
from parser import SemiformalParser, IntentNode
from generator import CodeGenerator, Mapping
from edit_router import EditTranslator, Edit, UpdateDecider
from edit_operations import EditResult
from config import MVPConfig, DEFAULT_CONFIG


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

        # Step 2: Generate Python (full generation, no existing code)
        self.python_code, self.mappings = self.generator.generate_with_mapping(
            self.intent_nodes,
            context=semiformal_code,
            existing_python=""  # Empty for full generation
        )

        # Step 3: Set up translator
        self.translator = EditTranslator(
            self.mappings,
            self.generator,
            self.config,
            self.intent_nodes  # Pass nodes for completeness-based routing
        )

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
        # If this is the first interaction, lazily initialize the editor state
        # from the current semiformal code. From the caller's perspective this
        # still looks like a normal "edit" (no separate initialize step).
        if not self.translator:
            init_result = self.initialize(self.semiformal_code)
            return {
                'success': True,
                'python_code': init_result['python_code'],
                'message': init_result['message'],
                'needs_regeneration': False,
                'regeneration_targets': [],
            }

        # Check if all semiformal code has been removed - if so, re-initialize
        # to reset mappings and state. This handles the case where user deletes
        # all content and we need to start fresh.
        semiformal_stripped = self.semiformal_code.strip() if self.semiformal_code else ""
        if not semiformal_stripped:
            # Empty or whitespace-only code - re-initialize to reset state
            init_result = self.initialize(self.semiformal_code)
            return {
                'success': True,
                'python_code': init_result['python_code'],
                'message': 'Reset mappings - all semiformal code removed',
                'needs_regeneration': False,
                'regeneration_targets': [],
            }
        
        # Also check if parsing results in no nodes (e.g., only comments/whitespace)
        # This catches cases where code exists but has no parseable content
        parsed_nodes = self.parser.parse(self.semiformal_code)
        if not parsed_nodes:
            # No parseable content - re-initialize to reset state
            init_result = self.initialize(self.semiformal_code)
            return {
                'success': True,
                'python_code': init_result['python_code'],
                'message': 'Reset mappings - no parseable content',
                'needs_regeneration': False,
                'regeneration_targets': [],
            }

        # Translate to Python edit
        result: EditResult = self.translator.semiformal_to_python(
            edit,
            self.semiformal_code,
            self.python_code
        )
        print('editor result', result)

        if result.success:
            # Apply the edit
            self.python_code = result.new_code

            # If the LLM pipeline returned updated nodes/mappings, refresh them
            # so /state and the frontend mapping stay in sync.
            # Regeneration is now handled directly in EditTranslator._llm_translate
            if result.new_nodes is not None:
                self.intent_nodes = result.new_nodes  # type: ignore[assignment]
            if result.new_mappings is not None:
                self.mappings = result.new_mappings  # type: ignore[assignment]
                # Update translator's internal mapping dict
                self.translator.mappings = {m.node_id: m for m in self.mappings}

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
        # Provide a simple suggestion for the user to update semiformal code
        suggestion = f"# Update semiformal code to reflect: {edit.content}"

        return {
            'success': True,
            'propagate': True,
            'message': f'Semantic change detected - suggest updating semiformal',
            'suggestion': suggestion,
            'strategy': strategy,
            'python_code': self.python_code
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
            'has_llm': getattr(self.generator.llm_service, "client", None) is not None
        }

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
