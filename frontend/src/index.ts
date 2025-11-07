/**
 * Main entry point for IR-based bidirectional programming.
 * 
 * New workflow:
 * - Continuous parsing as user edits spec
 * - Generation triggered on Cmd+S (save)
 * - No manual buttons
 * - Real-time feedback via decorations
 */

import { EditorView, keymap } from '@codemirror/view'
import { createEditor, getEditorContent, setEditorContent } from './editor'
import { DecorationManager, createDecorationPlugin } from './decorations'
import { analyzeSpec, generateCode, syncCodeToSpec, generateSkeleton, IncompleteNode } from './api'

// Initial example code
const EXAMPLE_SPEC = `result = process_data(raw_input)

x = split dataset into training and test sets

output = transform(x)

print(result, x, output)
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
  const statusBar = document.getElementById('status-bar')
  if (!statusBar) return

  statusBar.textContent = message
  statusBar.className = `status-bar ${type}`
  statusBar.style.display = 'block'

  if (type !== 'error') {
    setTimeout(() => {
      statusBar.style.display = 'none'
    }, 3000)
  }
}

// Initialize application
function init() {
  console.log('Initializing IR-based Semiformal Programming...')

  // Initialize managers
  specDecorationManager = new DecorationManager()

  // Create spec editor with save handler
  const specContainer = document.getElementById('spec-editor')
  if (!specContainer) {
    console.error('Spec editor container not found')
    return
  }

  specEditor = createEditor(
    specContainer,
    EXAMPLE_SPEC,
    [createDecorationPlugin(specDecorationManager)],
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

