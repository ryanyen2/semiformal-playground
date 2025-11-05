/**
 * API client for communicating with the backend.
 */

const API_BASE = '/api'

export interface IncompletePart {
  type: 'function' | 'variable' | 'nl_text'
  name: string
  line: number
  col: number
  context: string
  value?: string
}

export interface Stub {
  type: 'function' | 'variable'
  name: string
  insert_line: number
  code: string
  original_line: number
}

export interface ParseResult {
  incomplete_parts: IncompletePart[]
  stubs: Stub[]
  annotated_code: string
}

export interface GenerateResult {
  generated_code: string
  incomplete_parts: IncompletePart[]
}

export interface SyncResult {
  updated_code: string
  needs_regeneration: boolean
  regeneration_targets: string[]
  message: string
}

export class APIClient {
  async parse(code: string): Promise<ParseResult> {
    const response = await fetch(`${API_BASE}/parse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code })
    })

    if (!response.ok) {
      throw new Error(`Parse failed: ${response.statusText}`)
    }

    return response.json()
  }

  async generate(semiformalCode: string): Promise<GenerateResult> {
    const response = await fetch(`${API_BASE}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ semiformal_code: semiformalCode })
    })

    if (!response.ok) {
      throw new Error(`Generation failed: ${response.statusText}`)
    }

    return response.json()
  }

  async sync(
    direction: 'spec_to_code' | 'code_to_spec',
    editType: string,
    location: string,
    content: string,
    specCode: string,
    generatedCode: string,
    line?: number
  ): Promise<SyncResult> {
    const response = await fetch(`${API_BASE}/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        direction,
        edit_type: editType,
        location,
        content,
        spec_code: specCode,
        generated_code: generatedCode,
        line
      })
    })

    if (!response.ok) {
      throw new Error(`Sync failed: ${response.statusText}`)
    }

    return response.json()
  }

  async regenerate(
    functionName: string,
    currentCode: string,
    constraint: string,
    constraintType: string
  ): Promise<{ updated_code: string }> {
    const response = await fetch(`${API_BASE}/regenerate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        function_name: functionName,
        current_code: currentCode,
        constraint,
        constraint_type: constraintType
      })
    })

    if (!response.ok) {
      throw new Error(`Regeneration failed: ${response.statusText}`)
    }

    return response.json()
  }
}

export const api = new APIClient()
