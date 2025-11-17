/**
 * API client for communicating with the MVP backend.
 */

const API_BASE = '/api'

export interface IntentNode {
  type: string
  value: string
  line: number
  col: number
  metadata?: Record<string, any>
}

export interface NodeMapping {
  node_index: number
  code_line: number
  code_col: number
  code_snippet: string
}

export interface InitializeResponse {
  python_code: string
  nodes: IntentNode[]
  mappings: NodeMapping[]
  message: string
}

export interface EditResponse {
  success: boolean
  python_code: string
  message: string
  needs_regeneration?: boolean
  regeneration_targets?: string[]
}

export interface PythonEditResponse {
  success: boolean
  propagate: boolean
  message: string
  suggestion?: string
}

export interface StateResponse {
  semiformal_code: string
  python_code: string
  nodes: IntentNode[]
  mappings: NodeMapping[]
  has_llm: boolean
}

export class APIClient {
  /**
   * Initialize the editor with semiformal code.
   * This parses the code and generates initial Python code.
   */
  async initialize(semiformalCode: string): Promise<InitializeResponse> {
    const response = await fetch(`${API_BASE}/initialize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ semiformal_code: semiformalCode })
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(`Initialize failed: ${error.detail || response.statusText}`)
    }

    return response.json()
  }

  /**
   * Apply an edit to semiformal code.
   */
  async editSemiformal(
    location: string,
    content: string,
    semiformalCode: string,
    oldContent?: string,
    line?: number,
    metadata?: Record<string, any>
  ): Promise<EditResponse> {
    const response = await fetch(`${API_BASE}/edit/semiformal`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        location,
        content,
        old_content: oldContent,
        line,
        metadata,
        semiformal_code: semiformalCode
      })
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(`Edit failed: ${error.detail || response.statusText}`)
    }

    return response.json()
  }

  /**
   * Handle an edit to Python code.
   */
  async editPython(
    location: string,
    content: string,
    oldContent?: string,
    line?: number,
    metadata?: Record<string, any>
  ): Promise<PythonEditResponse> {
    const response = await fetch(`${API_BASE}/edit/python`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        location,
        content,
        old_content: oldContent,
        line,
        metadata
      })
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(`Python edit failed: ${error.detail || response.statusText}`)
    }

    return response.json()
  }

  /**
   * Get current editor state.
   */
  async getState(): Promise<StateResponse> {
    const response = await fetch(`${API_BASE}/state`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' }
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(`Get state failed: ${error.detail || response.statusText}`)
    }

    return response.json()
  }

  /**
   * Check backend health and capabilities.
   */
  async health(): Promise<{
    status: string
    service: string
    version: string
    phases: string[]
    has_openai: boolean
  }> {
    const response = await fetch(`${API_BASE}/`, {
      method: 'GET'
    })

    if (!response.ok) {
      throw new Error(`Health check failed: ${response.statusText}`)
    }

    return response.json()
  }
}

export const api = new APIClient()
