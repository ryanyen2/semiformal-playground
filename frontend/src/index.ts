/**
 * Main entry point for IR-based bidirectional programming.
 * 
 * New workflow:
 * - Continuous parsing as user edits spec
 * - Generation triggered on Cmd+S (save)
 * - No manual buttons
 * - Real-time feedback via decorations
 * Main entry point for the semiformal programming playground.
 *
 * Features:
 * - Auto-parse with 1-second debounce
 * - Cmd/Ctrl+S to generate code
 * - Bidirectional sync
 * - Cursor-based node mapping visualization
 */

import { EditorView, keymap } from '@codemirror/view'
import { createEditor, getEditorContent, setEditorContent } from './editor'
import { DecorationManager, createDecorationPlugin } from './decorations'
import { analyzeSpec, generateCode, syncCodeToSpec, generateSkeleton, IncompleteNode } from './api'
import { EditorView } from '@codemirror/view'
import { createEditor, getEditorContent } from './editor'
import {
  nodeDecorationsField,
  nodesStateField,
  cursorMappingStateField,
  pythonLineStateField,
  pythonLineDecorationsField,
  updateNodeDecorations,
  updateCursorMapping,
  updatePythonLineHighlight,
  findNodeAtCursor,
  findMappingForNode
} from './decorations'
import { api, IntentNode, NodeMapping } from './api'
import { ASTViewer } from './ast-viewer'

// Initial example code
const EXAMPLE_SPEC = `result = process_data(raw_input)

x = split dataset into training and test sets

output = transform(x)

print(result, x, output)
const EXAMPLE_SPEC = `result = load the dataset and process it

output = transform(result)

x, y = {split data into train and test}

print(output)
`

// Application state
let specEditor: EditorView
let codeEditor: EditorView
let specDecorationManager: DecorationManager

let lastSpecContent = EXAMPLE_SPEC
let lastCodeContent = ''
let isGenerating = false

// Debounce timer for continuous analysis
let analysisTimer: number | null = null
const ANALYSIS_DEBOUNCE_MS = 500

// Session ID for this editing session
const SESSION_ID = `session-${Date.now()}`

// Status bar management
function showStatus(message: string, type: 'info' | 'error' | 'success' = 'info') {
let astViewer: ASTViewer
let parseTimeout: number | null = null
let isGenerating = false
let isParsing = false

// Current state
let currentNodes: IntentNode[] = []
let currentMappings: NodeMapping[] = []
let hasLLM = false

/**
 * UI status helpers
 */
function setSpecStatus(text: string, className: '' | 'parsing' | 'generating' = '') {
  const dot = document.getElementById('spec-status-dot')
  const status = document.getElementById('spec-status-text')
  if (dot && status) {
    dot.className = `status-dot ${className}`
    status.textContent = text
  }
}

function setCodeStatus(text: string, className: '' | 'parsing' | 'generating' = '') {
  const dot = document.getElementById('code-status-dot')
  const status = document.getElementById('code-status-text')
  if (dot && status) {
    dot.className = `status-dot ${className}`
    status.textContent = text
  }
}

function setStatusMessage(message: string, type: '' | 'parsing' | 'generating' | 'error' | 'success' = '') {
  const statusBar = document.getElementById('status-bar')
  const statusMessage = document.getElementById('status-message')

  if (statusBar && statusMessage) {
    statusBar.className = `status-bar ${type}`
    statusMessage.textContent = message
  }
}

function setNodeCount(count: number) {
  const nodeCount = document.getElementById('node-count')
  if (nodeCount) {
    nodeCount.textContent = `${count} node${count !== 1 ? 's' : ''}`
  }
}

function setLLMStatus(available: boolean) {
  const llmStatus = document.getElementById('llm-status')
  if (llmStatus) {
    llmStatus.textContent = available ? 'LLM: available' : 'LLM: not configured'
    llmStatus.style.color = available ? '#4ec9b0' : '#858585'
  }
}

/**
 * Parse semiformal code (debounced)
 */
async function parseCode(semiformalCode: string) {
  if (isParsing) return
  isParsing = true

  try {
    setSpecStatus('Parsing...', 'parsing')
    setStatusMessage('Parsing semiformal code...', 'parsing')

    const result = await api.initialize(semiformalCode)

    currentNodes = result.nodes
    currentMappings = result.mappings

    // Update Python code editor with generated code
    codeEditor.dispatch({
      changes: {
        from: 0,
        to: codeEditor.state.doc.length,
        insert: result.python_code
      }
    })

    // Update decorations
    updateNodeDecorations(specEditor, result.nodes)

    // Update AST viewer
    astViewer.updateTree(result.nodes, result.mappings)

    // Update UI
    setNodeCount(result.nodes.length)
    setSpecStatus('Parsed', '')
    setCodeStatus('Generated', '')
    setStatusMessage(result.message, 'success')

    console.log('Parse result:', result)
  } catch (error) {
    console.error('Parse error:', error)
    setSpecStatus('Parse error', '')
    setStatusMessage(
      `Parse error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  } finally {
    isParsing = false
  }
}

/**
 * Generate Python code (Cmd+S)
 */
async function generateCode() {
  if (isGenerating || isParsing) return
  isGenerating = true

  try {
    const semiformalCode = getEditorContent(specEditor)

    setCodeStatus('Generating...', 'generating')
    setStatusMessage('Generating Python code...', 'generating')

    const result = await api.initialize(semiformalCode)

    // Update code editor
    codeEditor.dispatch({
      changes: {
        from: 0,
        to: codeEditor.state.doc.length,
        insert: result.python_code
      }
    })

    currentNodes = result.nodes
    currentMappings = result.mappings

    // Update decorations
    updateNodeDecorations(specEditor, result.nodes)

    // Update AST viewer
    astViewer.updateTree(result.nodes, result.mappings)

    // Update UI
    setCodeStatus('Generated', '')
    setStatusMessage(result.message, 'success')
    setNodeCount(result.nodes.length)

    console.log('Generation result:', result)
  } catch (error) {
    console.error('Generation error:', error)
    setCodeStatus('Generation error', '')
    setStatusMessage(
      `Generation error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  } finally {
    isGenerating = false
  }
}

/**
 * Calculate the length of the token to highlight based on node and mapping
 */
function calculateTokenLength(node: IntentNode, mapping: NodeMapping): number {
  // For identifiers and function calls, use the node value length
  if (node.type === 'identifier' || node.type === 'function_call') {
    return node.value.length
  }

  // For operators, use the node value length
  if (node.type === 'operator') {
    return node.value.length
  }

  // For literals, try to find the actual representation in the snippet
  if (node.type === 'literal') {
    // The snippet might have quotes around strings, so try to find the actual token
    const snippet = mapping.code_snippet
    const col = mapping.code_col
    
    // Extract the token starting at the column position
    if (snippet && col >= 0) {
      // Get the line from the snippet (in case it's multi-line)
      const lines = snippet.split('\n')
      if (lines.length > 0) {
        const firstLine = lines[0]
        // Try to extract a token starting at col
        const remaining = firstLine.substring(col)
        const tokenMatch = remaining.match(/^(\w+|'[^']*'|"[^"]*"|\d+\.?\d*|[^\s\w]+)/)
        if (tokenMatch) {
          return tokenMatch[1].length
        }
      }
    }
    return node.value.length
  }

  // For NL phrases and holes, highlight a reasonable portion of the generated code
  // Use the snippet to determine length
  const snippet = mapping.code_snippet
  if (snippet) {
    // For single-line snippets, use the whole snippet length
    const lines = snippet.split('\n')
    if (lines.length === 1) {
      return Math.min(snippet.length, 80) // Cap at 80 chars for readability
    }
    // For multi-line, highlight the first line
    return Math.min(lines[0].length - mapping.code_col, 80)
  }

  // Default fallback
  return Math.max(node.value.length, 5)
}

// Initialize application
function init() {
  console.log('Initializing IR-based Semiformal Programming...')
/**
 * Handle cursor movement to highlight mapped nodes
 */
function handleCursorMove(view: EditorView) {
  const cursorPos = view.state.selection.main.head
  const line = view.state.doc.lineAt(cursorPos)
  const lineNum = line.number
  const colNum = cursorPos - line.from

  // Find node at cursor
  const nodeIndex = findNodeAtCursor(currentNodes, lineNum, colNum)

  // Update cursor mapping
  updateCursorMapping(view, nodeIndex)

  // If there's a mapping, highlight the corresponding Python code
  if (nodeIndex !== null) {
    const mapping = findMappingForNode(currentMappings, nodeIndex)
    if (mapping) {
      const node = currentNodes[nodeIndex]
      console.log(`Cursor on node #${nodeIndex}:`, node)
      console.log(`Maps to Python line ${mapping.code_line}, col ${mapping.code_col}:`, mapping.code_snippet)

      // Calculate token length from node value or snippet
      // Try to extract the actual token from the snippet
      const tokenLength = calculateTokenLength(node, mapping)

      // Highlight the Python token in the code editor
      updatePythonLineHighlight(codeEditor, {
        line: mapping.code_line,
        col: mapping.code_col,
        length: tokenLength
      })
    } else {
      // Clear Python line highlight if no mapping
      updatePythonLineHighlight(codeEditor, null)
    }

    // Expand AST viewer to show this node
    astViewer.expandToNode(nodeIndex)
  } else {
    // Clear Python line highlight if no node
    updatePythonLineHighlight(codeEditor, null)
    astViewer.clearSelection()
  }
}

/**
 * Handle spec editor changes with debouncing
 */
function handleSpecChange() {
  // Clear existing timeout
  if (parseTimeout !== null) {
    clearTimeout(parseTimeout)
  }

  // Set new timeout for 1 second
  parseTimeout = window.setTimeout(() => {
    const semiformalCode = getEditorContent(specEditor)
    parseCode(semiformalCode)
  }, 1000)
}

/**
 * Initialize application
 */
async function init() {
  console.log('Initializing Semiformal Programming Playground...')

  // Initialize managers
  specDecorationManager = new DecorationManager()
  // Check backend health
  try {
    const health = await api.health()
    console.log('Backend health:', health)
    hasLLM = health.has_openai
    setLLMStatus(health.has_openai)

    if (!health.has_openai) {
      setStatusMessage('Warning: OpenAI API key not configured. LLM features disabled.', 'error')
    }
  } catch (error) {
    console.error('Backend not reachable:', error)
    setStatusMessage('Error: Backend not reachable. Make sure the server is running.', 'error')
    setLLMStatus(false)
  }

  // Create spec editor with save handler
  const specContainer = document.getElementById('spec-editor')
  if (!specContainer) {
    console.error('Spec editor container not found')
    return
  }

  specEditor = createEditor(
    specContainer,
    EXAMPLE_SPEC,
    [
      nodeDecorationsField,
      nodesStateField,
      cursorMappingStateField,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          handleSpecChange()
        }
        if (update.selectionSet) {
          handleCursorMove(update.view)
        }
      })
    ],
    false
  )

  // Add Cmd+S / Ctrl+S handler for generation
  specEditor.dom.addEventListener('keydown', (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault()
      handleSave()
    }
  })

  // Create code editor (read-only view)
  const codeContainer = document.getElementById('code-editor')
  if (!codeContainer) {
    console.error('Code editor container not found')
    return
  }

  codeEditor = createEditor(
    codeContainer,
    '# Generated code will appear here\n# Press Cmd+S (or Ctrl+S) in the spec editor to generate',
    [],
    '# Press Cmd+S in the left editor to generate Python code',
    [
      pythonLineStateField,
      pythonLineDecorationsField
    ],
    false
  )

  // Set up continuous analysis
  setupContinuousAnalysis()

  // Hide buttons (or remove them from HTML)
  hideButtons()

  console.log('Initialization complete!')
  showStatus('Ready! Edit spec on the left, press Cmd+S to generate code', 'success')

  // Initial analysis
  performAnalysis()
}

function hideButtons() {
  /**
   * Hide manual buttons since we have automatic workflow.
   */
  const buttons = ['parseBtn', 'generateBtn', 'syncToSpecBtn']
  buttons.forEach(id => {
    const btn = document.getElementById(id)
    if (btn) {
      btn.style.display = 'none'
    }
  })
}

function setupContinuousAnalysis() {
  /**
   * Set up continuous parsing as user edits.
   */
  // Listen for changes in spec editor
  const updateListener = EditorView.updateListener.of((update) => {
    if (update.docChanged) {
      // Debounce analysis
      if (analysisTimer) {
        clearTimeout(analysisTimer)
      }

      analysisTimer = window.setTimeout(() => {
        performAnalysis()
      }, ANALYSIS_DEBOUNCE_MS)
    }
  })

  // Add listener to spec editor
  specEditor.dispatch({
    effects: [
      // Note: This is simplified; proper implementation would add the listener
      // during editor creation in editor.ts
    ]
  })

  // Alternative: use MutationObserver or poll (less ideal)
  setInterval(() => {
    const currentContent = getEditorContent(specEditor)
    if (currentContent !== lastSpecContent) {
      lastSpecContent = currentContent
      performAnalysis()
    }
  }, ANALYSIS_DEBOUNCE_MS)
}

async function performAnalysis() {
  /**
   * Continuously analyze spec and generate skeleton (real-time sync).
   */
  const specCode = getEditorContent(specEditor)

  try {
    // Generate skeleton immediately (no LLM, fast)
    const skeletonResult = await generateSkeleton(specCode, SESSION_ID)
    
    // Update Python editor with skeleton
    setEditorContent(codeEditor, skeletonResult.skeleton_code)

    // Update decorations to show incomplete parts
    updateDecorations(skeletonResult.incomplete_nodes)

    // Update status bar
    const incompleteCount = skeletonResult.incomplete_nodes.length
    if (incompleteCount > 0) {
      showStatus(
        `${incompleteCount} incomplete element${incompleteCount > 1 ? 's' : ''} - Press Cmd+S to generate`,
        'info'
      )
    } else {
      showStatus('All elements complete', 'success')
    }

  } catch (error) {
    console.error('Analysis error:', error)
    // Don't show error toast for every analysis failure
  }
}

function updateDecorations(incompleteNodes: IncompleteNode[]) {
  /**
   * Update editor decorations based on incomplete nodes.
   */
  specDecorationManager.updateIncompleteParts(
    incompleteNodes.map(node => ({
      type: node.type as "function" | "variable" | "nl_text",
      name: node.name,
      line: node.line,
      col: 0,
      context: node.spec_text,
      value: node.metadata?.rhs ?? ''
    }))
  )
}

async function handleSave() {
  /**
   * Handle Cmd+S: trigger code generation.
   */
  if (isGenerating) {
    showStatus('Generation already in progress...', 'info')
    return
  }

  isGenerating = true
  showStatus('Generating code...', 'info')

  const specCode = getEditorContent(specEditor)

  try {
    const result = await generateCode(specCode, SESSION_ID)

    // Update code editor
    setEditorContent(codeEditor, result.generated_code)
    lastCodeContent = result.generated_code

    // Show success
    showStatus(
      `✓ Generated code (${result.affected_nodes.length} elements)`,
      'success'
    )

    // Optionally show diffs in console
    if (result.diffs.length > 0) {
      console.log('Generated diffs:')
      result.diffs.forEach(diff => {
        console.log(diff.diff_text)
      })
    }

  } catch (error) {
    console.error('Generation error:', error)
    showStatus(
      `Generation error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  } finally {
    isGenerating = false
  }
}

async function handleCodeEdit() {
  /**
   * Handle code editor changes (sync back to spec).
   * 
   * For now, this is manual. Could be automatic or triggered by save.
   */
  const currentCode = getEditorContent(codeEditor)

  if (currentCode === lastCodeContent) {
  // Create AST viewer
  const astViewerContainer = document.getElementById('ast-viewer')
  if (!astViewerContainer) {
    console.error('AST viewer container not found')
    return
  }

  try {
    const specCode = getEditorContent(specEditor)
    const result = await syncCodeToSpec(specCode, lastCodeContent, currentCode, SESSION_ID)

    // Update spec editor
    setEditorContent(specEditor, result.updated_spec)
    lastSpecContent = result.updated_spec
    lastCodeContent = currentCode

    showStatus('✓ Synced code changes to spec', 'success')

  } catch (error) {
    console.error('Sync error:', error)
    showStatus(
      `Sync error: ${error instanceof Error ? error.message : String(error)}`,
      'error'
    )
  }
}

// Keyboard shortcut hints
function showShortcutHints() {
  const hints = [
    'Cmd+S / Ctrl+S: Generate code from spec',
    'Continuous parsing: automatic as you type',
  ]

  console.log('Keyboard shortcuts:')
  hints.forEach(hint => console.log(`  ${hint}`))
  astViewer = new ASTViewer(astViewerContainer)

  // Set up AST viewer callbacks
  astViewer.setCallbacks({
    onNodeClick: (nodeIndex) => {
      // When clicking a node in the tree, highlight it in both editors
      const node = currentNodes[nodeIndex]
      const mapping = findMappingForNode(currentMappings, nodeIndex)

      // Highlight in spec editor
      updateCursorMapping(specEditor, nodeIndex)

      // Highlight in Python editor
      if (mapping) {
        const tokenLength = calculateTokenLength(node, mapping)
        updatePythonLineHighlight(codeEditor, {
          line: mapping.code_line,
          col: mapping.code_col,
          length: tokenLength
        })
      }
    }
  })

  // Add Cmd+S / Ctrl+S handler
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault()
      generateCode()
    }
  })

  console.log('Initialization complete!')
  setStatusMessage('Ready. Type to parse (auto-debounced) • Cmd+S to generate', 'success')

  // Initial parse
  parseCode(EXAMPLE_SPEC)
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    init()
    showShortcutHints()
  })
} else {
  init()
  showShortcutHints()
}

// Export for debugging
;(window as any).debugIR = {
  getSpec: () => getEditorContent(specEditor),
  getCode: () => getEditorContent(codeEditor),
  analyze: performAnalysis,
  generate: handleSave,
}

