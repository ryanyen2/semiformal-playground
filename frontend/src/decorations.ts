/**
 * CodeMirror decorations for semiformal programming with node mappings.
 */

import { Decoration, DecorationSet, EditorView, ViewPlugin, ViewUpdate, WidgetType } from '@codemirror/view'
import { RangeSetBuilder, StateField, StateEffect } from '@codemirror/state'
import type { IntentNode, NodeMapping } from './api'

/**
 * State effect to update decorations
 */
export const updateNodesEffect = StateEffect.define<IntentNode[]>()
export const updateMappingsEffect = StateEffect.define<NodeMapping[]>()
export const updateCursorMappingEffect = StateEffect.define<number | null>() // node index

/**
 * Create decorations based on intent nodes
 */
function createNodeDecorations(
  view: EditorView,
  nodes: IntentNode[],
  cursorNodeIndex: number | null
): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>()
  const doc = view.state.doc

  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i]

    // Skip if line is out of bounds
    if (node.line < 1 || node.line > doc.lines) {
      continue
    }

    const line = doc.line(node.line)
    const lineText = line.text

    // Find the node's position in the line
    let from = line.from + node.col
    let to = from + node.value.length

    // Ensure we don't go past line end
    if (to > line.to) {
      to = line.to
    }

    // Skip invalid ranges
    if (from >= to || from < line.from || to > line.to) {
      continue
    }

    // Determine decoration class based on node type
    let decorationClass = ''

    if (node.type === 'nl_phrase' || node.type === 'nl_text') {
      decorationClass = 'cm-nl-text'
    } else if (node.type === 'hole_empty' || node.type === 'hole') {
      decorationClass = 'cm-hole'
    } else if (node.type === 'hole_hint') {
      decorationClass = 'cm-hole-hint'
    } else if (node.type === 'placeholder') {
      decorationClass = 'cm-placeholder'
    }

    // Add highlight if this is the cursor-mapped node
    if (i === cursorNodeIndex) {
      decorationClass = `${decorationClass} cm-node-highlight`.trim()
    }

    if (decorationClass) {
      builder.add(
        from,
        to,
        Decoration.mark({
          class: decorationClass,
          attributes: {
            'data-node-index': String(i),
            'data-node-type': node.type,
            'data-node-value': node.value
          }
        })
      )
    }
  }

  return builder.finish()
}

/**
 * Gutter marker widget for showing mapping connections
 */
class MappingMarkerWidget extends WidgetType {
  constructor(readonly nodeIndex: number) {
    super()
  }

  toDOM() {
    const span = document.createElement('span')
    span.className = 'cm-mapping-marker'
    span.title = `Mapped node #${this.nodeIndex}`
    return span
  }

  eq(other: MappingMarkerWidget) {
    return other.nodeIndex === this.nodeIndex
  }
}

/**
 * Create gutter decorations for mapped lines
 */
function createMappingGutterDecorations(
  view: EditorView,
  mappings: NodeMapping[]
): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>()
  const doc = view.state.doc

  for (const mapping of mappings) {
    const lineNum = mapping.code_line

    if (lineNum < 1 || lineNum > doc.lines) {
      continue
    }

    const line = doc.line(lineNum)

    builder.add(
      line.from,
      line.from,
      Decoration.widget({
        widget: new MappingMarkerWidget(mapping.node_index),
        side: -1
      })
    )
  }

  return builder.finish()
}

/**
 * State field for managing node decorations
 */
export const nodeDecorationsField = StateField.define<DecorationSet>({
  create() {
    return Decoration.none
  },
  update(decorations, tr) {
    decorations = decorations.map(tr.changes)

    for (const effect of tr.effects) {
      if (effect.is(updateNodesEffect) || effect.is(updateCursorMappingEffect)) {
        const nodes = effect.is(updateNodesEffect)
          ? effect.value
          : tr.state.field(nodesStateField)
        const cursorMapping = effect.is(updateCursorMappingEffect)
          ? effect.value
          : tr.state.field(cursorMappingStateField)

        decorations = createNodeDecorations(tr.state.doc as any, nodes, cursorMapping)
      }
    }

    return decorations
  },
  provide: f => EditorView.decorations.from(f)
})

/**
 * State field for storing intent nodes
 */
export const nodesStateField = StateField.define<IntentNode[]>({
  create() {
    return []
  },
  update(nodes, tr) {
    for (const effect of tr.effects) {
      if (effect.is(updateNodesEffect)) {
        return effect.value
      }
    }
    return nodes
  }
})

/**
 * State field for storing cursor-mapped node index
 */
export const cursorMappingStateField = StateField.define<number | null>({
  create() {
    return null
  },
  update(index, tr) {
    for (const effect of tr.effects) {
      if (effect.is(updateCursorMappingEffect)) {
        return effect.value
      }
    }
    return index
  }
})

/**
 * State field for storing node mappings
 */
export const mappingsStateField = StateField.define<NodeMapping[]>({
  create() {
    return []
  },
  update(mappings, tr) {
    for (const effect of tr.effects) {
      if (effect.is(updateMappingsEffect)) {
        return effect.value
      }
    }
    return mappings
  }
})

/**
 * View plugin for managing decoration updates
 */
export const decorationPlugin = ViewPlugin.fromClass(class {
  decorations: DecorationSet

  constructor(view: EditorView) {
    this.decorations = Decoration.none
  }

  update(update: ViewUpdate) {
    if (update.docChanged || update.viewportChanged) {
      // Decorations are managed by state fields
    }
  }
}, {
  decorations: v => v.decorations
})

/**
 * Helper to update decorations from outside CodeMirror
 */
export function updateNodeDecorations(
  view: EditorView,
  nodes: IntentNode[]
) {
  view.dispatch({
    effects: updateNodesEffect.of(nodes)
  })
}

export function updateMappingDecorations(
  view: EditorView,
  mappings: NodeMapping[]
) {
  view.dispatch({
    effects: updateMappingsEffect.of(mappings)
  })
}

export function updateCursorMapping(
  view: EditorView,
  nodeIndex: number | null
) {
  view.dispatch({
    effects: updateCursorMappingEffect.of(nodeIndex)
  })
}

/**
 * Find which node the cursor is on
 */
export function findNodeAtCursor(
  nodes: IntentNode[],
  cursorLine: number,
  cursorCol: number
): number | null {
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i]
    if (node.line === cursorLine) {
      const nodeEnd = node.col + node.value.length
      if (cursorCol >= node.col && cursorCol <= nodeEnd) {
        return i
      }
    }
  }
  return null
}

/**
 * Find which Python code line maps to a node
 */
export function findMappingForNode(
  mappings: NodeMapping[],
  nodeIndex: number
): NodeMapping | null {
  return mappings.find(m => m.node_index === nodeIndex) || null
}

/**
 * State effect to update highlighted Python line
 */
export const updatePythonLineEffect = StateEffect.define<number | null>()

/**
 * State field for storing highlighted Python line
 */
export const pythonLineStateField = StateField.define<number | null>({
  create() {
    return null
  },
  update(lineNum, tr) {
    for (const effect of tr.effects) {
      if (effect.is(updatePythonLineEffect)) {
        return effect.value
      }
    }
    return lineNum
  }
})

/**
 * Create line highlight decoration for Python code
 */
function createPythonLineHighlight(
  view: EditorView,
  lineNum: number | null
): DecorationSet {
  if (lineNum === null || lineNum < 1) {
    return Decoration.none
  }

  const doc = view.state.doc
  if (lineNum > doc.lines) {
    return Decoration.none
  }

  const builder = new RangeSetBuilder<Decoration>()
  const line = doc.line(lineNum)

  // Add gutter marker
  builder.add(
    line.from,
    line.from,
    Decoration.widget({
      widget: new PythonLineMarkerWidget(),
      side: -1
    })
  )

  // Add line highlight
  builder.add(
    line.from,
    line.from,
    Decoration.line({
      class: 'cm-python-mapped-line'
    })
  )

  return builder.finish()
}

/**
 * Gutter marker for highlighted Python line
 */
class PythonLineMarkerWidget extends WidgetType {
  toDOM() {
    const span = document.createElement('span')
    span.className = 'cm-python-line-marker'
    span.style.cssText = `
      position: absolute;
      width: 3px;
      height: 100%;
      left: 0;
      background: linear-gradient(to right, #528bff, transparent);
    `
    return span
  }

  eq(other: PythonLineMarkerWidget) {
    return true
  }
}

/**
 * State field for Python line decorations
 */
export const pythonLineDecorationsField = StateField.define<DecorationSet>({
  create() {
    return Decoration.none
  },
  update(decorations, tr) {
    decorations = decorations.map(tr.changes)

    for (const effect of tr.effects) {
      if (effect.is(updatePythonLineEffect)) {
        decorations = createPythonLineHighlight(tr.state.doc as any, effect.value)
      }
    }

    return decorations
  },
  provide: f => EditorView.decorations.from(f)
})

/**
 * Update Python line highlight
 */
export function updatePythonLineHighlight(
  view: EditorView,
  lineNum: number | null
) {
  view.dispatch({
    effects: updatePythonLineEffect.of(lineNum)
  })
}
