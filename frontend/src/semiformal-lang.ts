/**
 * Custom syntax highlighting for semiformal programming constructs.
 * Extends Python syntax highlighting with support for:
 * - Holes: {} or {hint}
 * - Natural language phrases
 * - Incomplete Python code
 */

import { Extension } from '@codemirror/state'
import { Decoration, DecorationSet, ViewPlugin, ViewUpdate, EditorView } from '@codemirror/view'
import { RangeSetBuilder } from '@codemirror/state'

/**
 * Regex patterns for semiformal constructs
 */
const HOLE_PATTERN = /\{[^}]*\}/g
const ELLIPSIS_PATTERN = /\.\.\./g
const NL_ASSIGNMENT_PATTERN = /^(\s*\w+\s*=\s*)(.+)$/m

/**
 * Create decorations for semiformal constructs
 */
function createSemiformalDecorations(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>()
  const doc = view.state.doc
  
  for (let i = 1; i <= doc.lines; i++) {
    const line = doc.line(i)
    const lineText = line.text
    
    // Check for holes: {} or {hint}
    let match
    const holeRegex = new RegExp(HOLE_PATTERN)
    while ((match = holeRegex.exec(lineText)) !== null) {
      const from = line.from + match.index
      const to = from + match[0].length
      builder.add(
        from,
        to,
        Decoration.mark({
          class: 'cm-semiformal-hole',
          attributes: {
            'data-semiformal-type': 'hole'
          }
        })
      )
    }
    
    // Check for ellipsis (incomplete code)
    const ellipsisRegex = new RegExp(ELLIPSIS_PATTERN)
    while ((match = ellipsisRegex.exec(lineText)) !== null) {
      const from = line.from + match.index
      const to = from + match[0].length
      builder.add(
        from,
        to,
        Decoration.mark({
          class: 'cm-semiformal-ellipsis',
          attributes: {
            'data-semiformal-type': 'ellipsis'
          }
        })
      )
    }
    
    // Check for NL assignments: identifier = natural language text
    // Heuristic: if RHS doesn't look like Python code, treat as NL
    if (lineText.includes('=') && !lineText.trim().startsWith('#')) {
      const equalsIndex = lineText.indexOf('=')
      const lhs = lineText.substring(0, equalsIndex).trim()
      const rhs = lineText.substring(equalsIndex + 1).trim()
      
      // Check if LHS looks like a valid identifier (possibly with commas for multiple assignment)
      const lhsIsValid = /^[a-zA-Z_][a-zA-Z0-9_]*(\s*,\s*[a-zA-Z_][a-zA-Z0-9_]*)*$/.test(lhs)
      
      if (lhsIsValid && rhs.length > 0) {
        // Check if RHS is likely NL (not Python)
        // Python indicators: starts with quote, number, bracket, or valid Python expression
        const rhsStartsWithPython = /^(['"`]|\d|\[|\{|\(|\w+\()/.test(rhs)
        
        // Check if RHS contains hole syntax (already handled above)
        const hasHole = rhs.includes('{') && rhs.includes('}')
        
        // Check if RHS is ellipsis (already handled above)
        const isEllipsis = rhs === '...'
        
        // If RHS doesn't start with Python-like syntax and isn't a hole/ellipsis,
        // and contains spaces (likely NL phrase), highlight as NL
        if (!rhsStartsWithPython && !hasHole && !isEllipsis && rhs.includes(' ')) {
          // Additional check: if it looks like a sentence (contains common words)
          const looksLikeNL = /\b(the|a|an|is|are|was|were|to|of|in|on|at|for|with|by)\b/i.test(rhs) ||
                             (rhs.split(' ').length >= 2 && !/[+\-*/%=<>!&|()[\]{}]/.test(rhs))
          
          if (looksLikeNL) {
            const equalsPos = lineText.indexOf('=')
            const rhsStart = line.from + equalsPos + 1
            // Skip whitespace after =
            let actualStart = rhsStart
            while (actualStart < line.to && /\s/.test(lineText[actualStart - line.from])) {
              actualStart++
            }
            
            if (actualStart < line.to) {
              builder.add(
                actualStart,
                line.to,
                Decoration.mark({
                  class: 'cm-semiformal-nl',
                  attributes: {
                    'data-semiformal-type': 'nl-phrase'
                  }
                })
              )
            }
          }
        }
      }
    }
  }
  
  return builder.finish()
}

/**
 * Plugin that provides syntax highlighting for semiformal constructs
 */
const semiformalHighlightPlugin = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet
    
    constructor(view: EditorView) {
      this.decorations = createSemiformalDecorations(view)
    }
    
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.decorations = createSemiformalDecorations(update.view)
      }
    }
  },
  {
    decorations: (v) => v.decorations
  }
)

/**
 * Extension for semiformal syntax highlighting
 */
export function semiformalHighlighting(): Extension {
  return semiformalHighlightPlugin
}

