/**
 * API client for IR-based backend.
 */

const API_BASE = 'http://localhost:8000'

// Types matching backend IR structure

export interface SourceLocation {
  line: number
  col: number
  end_line: number | null
  end_col: number | null
}

export interface IRNode {
  id: string
  type: string  // NodeType enum value
  name: string
  status: string  // NodeStatus enum value
  spec_text: string
  code_text: string
  spec_location: SourceLocation | null
  code_location: SourceLocation | null
  metadata: Record<string, any>
}

export interface ProgramIR {
  nodes: Record<string, IRNode>
  spec_source: string
  code_source: string
  dependency_graph: Record<string, string[]>
}

export interface ASTMapping {
  node_id: string
  line: number
  col_start: number
  col_end: number
  code_text: string
  confidence: number
  mapping_type: string  // 'exact', 'semantic', 'inferred'
}

// API Responses

export interface ParseResponse {
  ir: ProgramIR
  incomplete_nodes: IRNode[]
  skeleton_code: string
}

export interface GenerateResponse {
  generated_code: string
  ir: ProgramIR
  mappings: Record<string, ASTMapping>
}

export interface EditSemiformalResponse {
  updated_code: string
  needs_regeneration: boolean
  affected_nodes: string[]
  message: string
}

export interface EditCodeResponse {
  updated_semiformal: string
  message: string
}

export interface SkeletonResponse {
  skeleton_code: string
  incomplete_count: number
}

export interface MappingsResponse {
  mappings: Record<string, ASTMapping>
  ir: ProgramIR
}

// API Functions

/**
 * Parse semiformal code and build IR.
 */
export async function parse(code: string): Promise<ParseResponse> {
  const response = await fetch(`${API_BASE}/parse`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ code }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Parse failed')
  }

  return response.json()
}

/**
 * Generate complete Python code from semiformal specification.
 * Uses LLM to generate code with comment anchors.
 */
export async function generate(semiformalCode: string): Promise<GenerateResponse> {
  const response = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ semiformal_code: semiformalCode }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Generation failed')
  }

  return response.json()
}

/**
 * Handle edits to semiformal code.
 *
 * Two modes:
 * - 'code_node_edit': Direct structural edit (no LLM, fast)
 * - 'nl_phrase_edit': NL phrase changed, needs LLM refinement
 */
export async function editSemiformal(
  semiformalCode: string,
  editType: 'code_node_edit' | 'nl_phrase_edit',
  nodeId?: string,
  newContent?: string
): Promise<EditSemiformalResponse> {
  const response = await fetch(`${API_BASE}/edit/semiformal`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      semiformal_code: semiformalCode,
      edit_type: editType,
      node_id: nodeId,
      new_content: newContent,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Edit failed')
  }

  return response.json()
}

/**
 * Handle edits to generated code.
 * Syncs changes back to semiformal spec.
 */
export async function editCode(
  semiformalCode: string,
  generatedCode: string,
  oldCode: string,
  newCode: string
): Promise<EditCodeResponse> {
  const response = await fetch(`${API_BASE}/edit/code`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      semiformal_code: semiformalCode,
      generated_code: generatedCode,
      old_code: oldCode,
      new_code: newCode,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Code edit failed')
  }

  return response.json()
}

/**
 * Generate instant skeleton without LLM.
 * Called on every keystroke for fast feedback.
 */
export async function skeleton(semiformalCode: string): Promise<SkeletonResponse> {
  const response = await fetch(`${API_BASE}/skeleton`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ semiformal_code: semiformalCode }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Skeleton generation failed')
  }

  return response.json()
}

/**
 * Get fine-grained mappings between IR nodes and AST nodes.
 * Used for highlighting and navigation.
 */
export async function getMappings(
  semiformalCode: string,
  generatedCode: string
): Promise<MappingsResponse> {
  const response = await fetch(`${API_BASE}/mappings`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      semiformal_code: semiformalCode,
      generated_code: generatedCode,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Mappings failed')
  }

  return response.json()
}
