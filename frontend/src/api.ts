/**
 * API client for IR-based backend.
 */

const API_BASE = 'http://localhost:8000'

export interface IncompleteNode {
  id: string
  type: string
  name: string
  spec_text: string
  line: number
  status: string
  metadata: Record<string, any>
}

export interface CompleteNode {
  id: string
  type: string
  name: string
  spec_text: string
  line: number
}

export interface AnalyzeResult {
  incomplete_nodes: IncompleteNode[]
  complete_nodes: CompleteNode[]
  dependencies: Record<string, string[]>
  needs_generation: boolean
  message: string
}

export interface DiffHunk {
  old_start: number
  old_count: number
  new_start: number
  new_count: number
  lines: string[]
}

export interface Diff {
  old_file: string
  new_file: string
  hunks: DiffHunk[]
  diff_text: string
}

export interface GenerateResult {
  generated_code: string
  diffs: Diff[]
  affected_nodes: string[]
  message: string
}

export interface SyncCodeResult {
  updated_spec: string
  diffs: Diff[]
  affected_nodes: string[]
  message: string
}

export interface IRState {
  ir: Record<string, any>
  spec_source: string
  code_source: string
}

export interface SkeletonResult {
  skeleton_code: string
  incomplete_nodes: IncompleteNode[]
  message: string
}

export interface StateResponse {
  semiformal_code: string
  python_code: string
  nodes: IntentNode[]
  mappings: NodeMapping[]
  has_llm: boolean
}

/**
 * Generate Python skeleton without LLM (instant).
 */
export async function generateSkeleton(
  specCode: string,
  sessionId: string = 'default'
): Promise<SkeletonResult> {
  const response = await fetch(`${API_BASE}/skeleton`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      spec_code: specCode,
      session_id: sessionId,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Skeleton generation failed')
  }

  return response.json()
}

/**
 * Analyze spec code (continuous parsing).
 */
export async function analyzeSpec(
  specCode: string,
  sessionId: string = 'default'
): Promise<AnalyzeResult> {
  const response = await fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      spec_code: specCode,
      session_id: sessionId,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Analysis failed')
  }

  return response.json()
}

/**
 * Generate code from spec (triggered on save).
 */
export async function generateCode(
  specCode: string,
  sessionId: string = 'default'
): Promise<GenerateResult> {
  const response = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      spec_code: specCode,
      session_id: sessionId,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Generation failed')
  }

  return response.json()
}

/**
 * Sync code changes back to spec.
 */
export async function syncCodeToSpec(
  specCode: string,
  oldCode: string,
  newCode: string,
  sessionId: string = 'default'
): Promise<SyncCodeResult> {
  const response = await fetch(`${API_BASE}/sync-code`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      spec_code: specCode,
      old_code: oldCode,
      new_code: newCode,
      session_id: sessionId,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Sync failed')
  }

  return response.json()
}

/**
 * Get current IR state.
 */
export async function getIRState(
  sessionId: string = 'default'
): Promise<IRState> {
  const response = await fetch(`${API_BASE}/get-ir`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      session_id: sessionId,
    }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.detail || 'Failed to get IR state')
  }

  return response.json()
}

/**
 * WebSocket connection for real-time sync.
 */
export class SyncWebSocket {
  private ws: WebSocket | null = null
  private sessionId: string
  private onAnalysisCallback?: (data: any) => void
  private onGenerationCallback?: (data: any) => void
  private onErrorCallback?: (error: string) => void

  constructor(sessionId: string = 'default') {
    this.sessionId = sessionId
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const wsUrl = `ws://localhost:8000/ws/${this.sessionId}`
      this.ws = new WebSocket(wsUrl)

      this.ws.onopen = () => {
        console.log('WebSocket connected')
        resolve()
      }

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        reject(error)
      }

      this.ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          
          if (message.type === 'analysis' && this.onAnalysisCallback) {
            this.onAnalysisCallback(message)
          } else if (message.type === 'generation' && this.onGenerationCallback) {
            this.onGenerationCallback(message)
          } else if (message.type === 'error' && this.onErrorCallback) {
            this.onErrorCallback(message.message)
          }
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }

      this.ws.onclose = () => {
        console.log('WebSocket disconnected')
      }
    })
  }

  sendAnalyze(specCode: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'analyze',
        spec_code: specCode,
      }))
    }
  }

  sendGenerate(specCode: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'generate',
        spec_code: specCode,
      }))
    }
  }

  onAnalysis(callback: (data: any) => void): void {
    this.onAnalysisCallback = callback
  }

  onGeneration(callback: (data: any) => void): void {
    this.onGenerationCallback = callback
  }

  onError(callback: (error: string) => void): void {
    this.onErrorCallback = callback
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }
}

