/**
 * Main entry point for the semiformal programming playground.
 *
 * Features:
 * - Auto-parse with 1-second debounce
 * - Cmd/Ctrl+S to generate code
 * - Bidirectional sync
 * - Cursor-based node mapping visualization
 */

import { EditorView } from '@codemirror/view'
import { createEditor, getEditorContent, detectChanges, type ChangeInfo } from './editor'
import {
  nodeDecorationsField,
  nodesStateField,
  cursorMappingStateField,
  pythonLineStateField,
  pythonLineDecorationsField,
  unmappedCodeStateField,
  unmappedCodeDecorationsField,
  changedLinesStateField,
  changedLinesGutter,
  updateNodeDecorations,
  updateCursorMapping,
  updatePythonLineHighlight,
  updateUnmappedCodeRegions,
  updateChangedLines,
  findNodeAtCursor,
  findMappingForNode
} from './decorations'
import { api, IntentNode, NodeMapping } from './api'
import { ASTViewer } from './ast-viewer'

// Initial example code
const EXAMPLE_SPEC = `
`

// Application state
let specEditor: EditorView
let codeEditor: EditorView
let astViewer: ASTViewer
let parseTimeout: number | null = null
let isGenerating = false
let isParsing = false

// Current state
let currentNodes: IntentNode[] = []
let currentMappings: NodeMapping[] = []
let lastSpecCode = ''
let lastPythonCode = ''
let hasLLM = false
let currentInferredInsertions: Array<{code: string, insert_line: number | null, func_name: string}> = []
let lastInsertedFunctions = new Set<string>()
let isInsertingInferredCode = false  // Flag to prevent insertion loops
let inferredInsertionAttempts = 0  // Counter to prevent infinite loops
const MAX_INSERTION_ATTEMPTS = 3  // Maximum number of insertion cycles
let lastInsertionHash = ''  // Hash of last insertion to detect duplicates
let insertionCooldownUntil = 0  // Timestamp when cooldown ends

/**
 * Check if a function definition already exists in the spec
 */
function functionExistsInSpec(content: string, funcName: string, funcSignature?: string): boolean {
  // Check for function definition pattern: def func_name(
  const funcDefPattern = new RegExp(`^\\s*def\\s+${funcName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\(`, 'm')
  if (funcDefPattern.test(content)) {
    return true
  }
  
  // Also check for exact signature match if provided
  if (funcSignature) {
    const normalizedSig = funcSignature.trim().replace(/\s+/g, ' ')
    const lines = content.split('\n')
    for (const line of lines) {
      const normalizedLine = line.trim().replace(/\s+/g, ' ')
      if (normalizedLine.startsWith('def ') && normalizedLine.includes(funcName + '(')) {
        // Extract signature from line
        const sigMatch = normalizedLine.match(/def\s+\w+\s*\([^)]*\)/)
        if (sigMatch && sigMatch[0] === normalizedSig) {
          return true
        }
      }
    }
  }
  
  return false
}

/**
 * Automatically insert inferred code to spec editor at the correct position
 * Also handles function body replacements for existing stubs
 */
function insertInferredCodeToSpec(insertions: Array<{
  code: string, 
  insert_line: number | null, 
  func_name: string,
  is_replacement?: boolean,
  replace_start_line?: number,
  replace_end_line?: number
}>) {
  if (!insertions || insertions.length === 0) return
  if (isInsertingInferredCode) return  // Prevent recursive insertion
  
  // Check if we're in cooldown period
  const now = Date.now()
  if (now < insertionCooldownUntil) {
    const remainingSeconds = Math.ceil((insertionCooldownUntil - now) / 1000)
    console.warn(`In cooldown period, ${remainingSeconds}s remaining. Skipping insertion to prevent loop.`)
    return
  }
  
  // Check insertion attempts limit
  if (inferredInsertionAttempts >= MAX_INSERTION_ATTEMPTS) {
    console.warn(`Reached maximum insertion attempts (${MAX_INSERTION_ATTEMPTS}), entering 10s cooldown to prevent loop`)
    insertionCooldownUntil = now + 10000  // 10 second cooldown
    inferredInsertionAttempts = 0  // Reset for next cycle
    return
  }
  
  // Create a hash of the insertions to detect duplicates
  const insertionHash = insertions.map(i => `${i.func_name}:${i.code.substring(0, 50)}`).join('|')
  if (insertionHash === lastInsertionHash) {
    console.warn('Duplicate insertion detected, skipping to prevent loop')
    return
  }
  
  isInsertingInferredCode = true
  inferredInsertionAttempts++
  lastInsertionHash = insertionHash
  
  try {
    const currentContent = getEditorContent(specEditor)
    const lines = currentContent.split('\n')
    let newContent = currentContent
    let hasChanges = false
    
    // Sort insertions by insert_line (nulls last, descending order to insert from bottom up)
    const sortedInsertions = [...insertions].sort((a, b) => {
      if (a.insert_line === null && b.insert_line === null) return 0
      if (a.insert_line === null) return 1
      if (b.insert_line === null) return -1
      return b.insert_line - a.insert_line  // Descending order
    })
    
    for (const insertion of sortedInsertions) {
      const funcName = insertion.func_name
      const code = insertion.code.trim()
      const isReplacement = insertion.is_replacement || false
      
      // Handle replacement (update existing function body)
      if (isReplacement && insertion.replace_start_line !== undefined && insertion.replace_end_line !== undefined) {
        const startLine = insertion.replace_start_line  // 0-indexed
        const endLine = insertion.replace_end_line  // 0-indexed
        
        if (startLine >= 0 && endLine >= startLine && endLine < lines.length) {
          // Remove old function
          lines.splice(startLine, endLine - startLine + 1)
          // Insert new function at same position
          lines.splice(startLine, 0, ...code.split('\n'))
          hasChanges = true
          lastInsertedFunctions.add(funcName)
          console.log(`Replaced function body for: ${funcName}`)
          continue
        } else {
          console.warn(`Invalid replacement range for ${funcName}: ${startLine}-${endLine}`)
          // Fall through to insertion logic
        }
      }
      
      // Skip standalone insertions that start with __standalone_
      if (funcName.startsWith('__standalone_')) {
        // For standalone code, check if it's already present more carefully
        const codeLines = code.split('\n')
        const firstLine = codeLines[0]?.trim()
        if (firstLine && currentContent.includes(firstLine)) {
          continue
        }
      } else {
        // For function definitions, check if function already exists
        // Extract function signature from code
        const funcSigMatch = code.match(/^def\s+\w+\s*\([^)]*\)/)
        const funcSignature = funcSigMatch ? funcSigMatch[0] : undefined
        
        if (functionExistsInSpec(currentContent, funcName, funcSignature)) {
          lastInsertedFunctions.add(funcName)
          continue
        }
        
        // Also check if we've already inserted this function in this session
        if (lastInsertedFunctions.has(funcName)) {
          continue
        }
      }
      
      // Determine insertion position
      let insertPos: number
      
      if (insertion.insert_line !== null && insertion.insert_line > 0) {
        // Insert above the call site (1-based line number)
        // Convert to 0-based index
        const lineIndex = insertion.insert_line - 1
        if (lineIndex >= 0 && lineIndex < lines.length) {
          insertPos = lineIndex
        } else {
          // Invalid line, append at end
          insertPos = lines.length
        }
      } else {
        // No insert_line specified, append at end
        insertPos = lines.length
      }
      
      // Insert the function definition
      // Add separator before if needed
      if (insertPos > 0 && lines[insertPos - 1].trim() !== '') {
        // Add blank line before if previous line is not empty
        lines.splice(insertPos, 0, '')
        insertPos += 1
      }
      lines.splice(insertPos, 0, ...code.split('\n'))
      hasChanges = true
      
      // Mark as inserted (for function definitions)
      if (!funcName.startsWith('__standalone_')) {
        lastInsertedFunctions.add(funcName)
      }
    }
  
  if (hasChanges) {
    newContent = lines.join('\n')
    
    // Update editor content
    specEditor.dispatch({
      changes: {
        from: 0,
        to: specEditor.state.doc.length,
        insert: newContent
      }
    })
    
    // Trigger parse (which will regenerate code)
    // Use a small delay to ensure the editor update is complete
    setTimeout(() => {
      isInsertingInferredCode = false
      parseCode(newContent)
    }, 100)
  } else {
    // No changes made - reset counters since we're not causing a regeneration
    isInsertingInferredCode = false
    inferredInsertionAttempts = 0
    lastInsertionHash = ''
  }
  } finally {
    // Ensure flag is reset even if there's an error
    if (isInsertingInferredCode) {
      setTimeout(() => {
        isInsertingInferredCode = false
      }, 200)
    }
  }
}

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
    llmStatus.style.color = available ? '#28a745' : '#586069'
  }
}

/**
 * Apply a semiformal edit through the unified /edit/semiformal endpoint.
 * The backend decides whether this is an initial generation or a refinement.
 */
async function applySemiformalEdit(oldCode: string, newCode: string) {
  if (isParsing) return
  isParsing = true

  try {
    setSpecStatus('Parsing...', 'parsing')
    setStatusMessage('Parsing semiformal code...', 'parsing')

    const newLines = newCode.split('\n')
    const oldLines = oldCode.split('\n')

    // Compute a minimal change description to send to the backend.
    let change: ChangeInfo | null = null
    if (oldCode && oldCode !== newCode) {
      change = detectChanges(oldCode, newCode)
    }

    const hasPrevious = !!oldCode
    const fromLine = change ? change.fromLine : 0
    const newLineText = newLines[fromLine] ?? ''
    const oldLineText = hasPrevious ? oldLines[fromLine] ?? '' : undefined

    const editResult = await api.editSemiformal(
      String(fromLine),
      newLineText,
      newCode,
      oldLineText,
      fromLine,
      {
        from_side: 'semiformal'
      }
    )

    // Update Python code editor with generated/refined code
    codeEditor.dispatch({
      changes: {
        from: 0,
        to: codeEditor.state.doc.length,
        insert: editResult.python_code
      }
    })

    lastSpecCode = newCode
    lastPythonCode = editResult.python_code

    // Refresh nodes and mappings from backend state so mapping/AST stay in sync
    const state = await api.getState()
    currentNodes = state.nodes
    currentMappings = state.mappings
    
    // Update changed lines if available
    if (editResult.changed_lines && editResult.changed_lines.length > 0) {
      updateChangedLines(codeEditor, editResult.changed_lines)
    } else {
      updateChangedLines(codeEditor, [])
    }

    // Update inferred insertions and automatically insert them at correct positions
    // Only insert if we're not already in an insertion cycle
    if (!isInsertingInferredCode) {
      const inferredInsertions = editResult.inferred_insertions || state.inferred_insertions || []
      if (inferredInsertions.length > 0) {
        // Only insert if we have new insertions that aren't already in the spec
        const insertionKeys = new Set(inferredInsertions.map(i => i.func_name))
        const currentKeys = new Set(currentInferredInsertions.map(i => i.func_name))
        
        // Check if we have genuinely new insertions
        const hasNewInsertions = insertionKeys.size !== currentKeys.size || 
            !Array.from(insertionKeys).every(k => currentKeys.has(k))
        
        if (hasNewInsertions) {
          // Also verify that these functions don't already exist in the spec
          const currentContent = getEditorContent(specEditor)
          const trulyNew = inferredInsertions.filter(ins => {
            if (ins.func_name.startsWith('__standalone_')) {
              return true  // Always check standalone
            }
            const funcSigMatch = ins.code.match(/^def\s+\w+\s*\([^)]*\)/)
            const funcSignature = funcSigMatch ? funcSigMatch[0] : undefined
            return !functionExistsInSpec(currentContent, ins.func_name, funcSignature)
          })
          
          if (trulyNew.length > 0) {
            currentInferredInsertions = inferredInsertions
            // Automatically insert inferred code at the correct positions
            insertInferredCodeToSpec(trulyNew)
          } else {
            // Update tracking even if we don't insert
            currentInferredInsertions = inferredInsertions
          }
        } else {
          // Update tracking
          currentInferredInsertions = inferredInsertions
        }
      }
    }

    // Update decorations
    updateNodeDecorations(specEditor, currentNodes)
    
    // Update unmapped code decorations in Python editor
    if (state.unmapped_code && state.unmapped_code.length > 0) {
      updateUnmappedCodeRegions(codeEditor, state.unmapped_code)
    } else {
      updateUnmappedCodeRegions(codeEditor, [])
    }

    // Update AST viewer
    astViewer.updateTree(currentNodes, currentMappings)

    // Update UI
    setNodeCount(currentNodes.length)
    setSpecStatus('Parsed', '')
    setCodeStatus('Generated', '')
    setStatusMessage(editResult.message, 'success')

    console.log('Semiformal edit result:', editResult)
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
 * Parse semiformal code (debounced) using the unified edit pipeline.
 */
async function parseCode(semiformalCode: string) {
  await applySemiformalEdit(lastSpecCode, semiformalCode)
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

    await applySemiformalEdit(lastSpecCode, semiformalCode)

    setCodeStatus('Generated', '')
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

  // Reset insertion tracking when user manually edits the spec
  // (Unless we're in the middle of an auto-insertion)
  if (!isInsertingInferredCode) {
    inferredInsertionAttempts = 0
    lastInsertionHash = ''
    insertionCooldownUntil = 0  // Clear cooldown on manual edit
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

  // Create spec editor
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
    false,
    true // Enable semiformal syntax highlighting for spec editor
  )

  // Create code editor
  const codeContainer = document.getElementById('code-editor')
  if (!codeContainer) {
    console.error('Code editor container not found')
    return
  }

  codeEditor = createEditor(
    codeContainer,
    '# Press Cmd+S in the left editor to generate Python code',
    [
      pythonLineStateField,
      pythonLineDecorationsField,
      unmappedCodeStateField,
      unmappedCodeDecorationsField,
      changedLinesStateField,
      changedLinesGutter  // Add gutter for changed lines
    ],
    false
  )

  // Create AST viewer
  const astViewerContainer = document.getElementById('ast-viewer')
  if (!astViewerContainer) {
    console.error('AST viewer container not found')
    return
  }

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

  // Initial parse (treated as first edit with no previous code)
  lastSpecCode = ''
  lastPythonCode = ''
  parseCode(EXAMPLE_SPEC)
}

// Start the application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init)
} else {
  init()
}
