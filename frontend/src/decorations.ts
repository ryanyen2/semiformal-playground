/**
 * CodeMirror decorations for incomplete code parts.
 */

import { Decoration, DecorationSet, EditorView, ViewPlugin, ViewUpdate } from '@codemirror/view'
import { RangeSetBuilder } from '@codemirror/state'
import type { IncompletePart, Stub } from './api'

/**
 * Create decorations for incomplete parts and stubs.
 */
export function createDecorations(
  view: EditorView,
  incompleteParts: IncompletePart[],
  stubs: Stub[]
): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>()
  const doc = view.state.doc

  // Add decorations for incomplete parts (grayed out NL text)
  for (const part of incompleteParts) {
    if (part.type === 'nl_text') {
      // Find the line and mark NL text as grayed out
      const lineNum = part.line
      if (lineNum > 0 && lineNum <= doc.lines) {
        const line = doc.line(lineNum)
        const lineText = line.text

        // Find the NL text portion (after the '=')
        const eqIndex = lineText.indexOf('=')
        if (eqIndex >= 0) {
          const nlStart = line.from + eqIndex + 1
          const nlEnd = line.to

          builder.add(
            nlStart,
            nlEnd,
            Decoration.mark({
              class: 'cm-incomplete',
              attributes: { 'data-incomplete-type': 'nl-text' }
            })
          )
        }
      }
    }
  }

  // Add decorations for stub declarations
  for (const stub of stubs) {
    const lineNum = stub.insert_line + 1 // Convert to 1-based
    if (lineNum > 0 && lineNum <= doc.lines) {
      const line = doc.line(lineNum)

      // Mark the entire stub line
      builder.add(
        line.from,
        line.to,
        Decoration.mark({
          class: 'cm-stub',
          attributes: {
            'data-stub-type': stub.type,
            'data-stub-name': stub.name
          }
        })
      )
    }
  }

  return builder.finish()
}

/**
 * View plugin to manage decorations.
 */
export class DecorationManager {
  private incompleteParts: IncompletePart[] = []
  private stubs: Stub[] = []

  updateIncompleteParts(parts: IncompletePart[]) {
    this.incompleteParts = parts
  }

  updateStubs(stubs: Stub[]) {
    this.stubs = stubs
  }

  getIncompleteParts(): IncompletePart[] {
    return this.incompleteParts
  }

  getStubs(): Stub[] {
    return this.stubs
  }
}

/**
 * Create a CodeMirror view plugin for managing decorations.
 */
export function createDecorationPlugin(manager: DecorationManager) {
  return ViewPlugin.define(
    (view) => ({
      decorations: createDecorations(view, manager.getIncompleteParts(), manager.getStubs()),

      update(update: ViewUpdate) {
        if (update.docChanged || update.viewportChanged) {
          this.decorations = createDecorations(
            update.view,
            manager.getIncompleteParts(),
            manager.getStubs()
          )
        }
      }
    }),
    {
      decorations: (v) => v.decorations
    }
  )
}

/**
 * Create line decorations for highlighting specific lines.
 */
export function createLineHighlight(lineNum: number, className: string) {
  return Decoration.line({
    class: className
  })
}
