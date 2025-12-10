/**
 * CodeMirror decorations for semiformal programming with node mappings.
 */

import { Decoration, DecorationSet, EditorView, WidgetType, GutterMarker, gutter } from '@codemirror/view'
import { RangeSetBuilder, StateField, StateEffect } from '@codemirror/state'
import type { IntentNode, NodeMapping, UnmappedCodeRegion } from './api'

/**
 * State effect to update decorations
 */
export const updateNodesEffect = StateEffect.define<IntentNode[]>()
export const updateCursorMappingEffect = StateEffect.define<number | null>()
export const updateChangedLinesEffect = StateEffect.define<number[]>()  // NEW: Track changed lines

/**
 * Create decorations based on intent nodes
 */
function createNodeDecorations(
  doc: { lines: number; line: (n: number) => { from: number; to: number; text: string } },
  nodes: IntentNode[],
  cursorNodeIndex: number | null
): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>()

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

        decorations = createNodeDecorations(tr.state.doc, nodes, cursorMapping)
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
 * Token highlight information
 */
export interface PythonTokenHighlight {
  line: number
  col: number
  length: number
}

/**
 * State effect to update highlighted Python token
 */
export const updatePythonLineEffect = StateEffect.define<PythonTokenHighlight | null>()

/**
 * State field for storing highlighted Python token
 */
export const pythonLineStateField = StateField.define<PythonTokenHighlight | null>({
  create() {
    return null
  },
  update(highlight, tr) {
    for (const effect of tr.effects) {
      if (effect.is(updatePythonLineEffect)) {
        return effect.value
      }
    }
    return highlight
  }
})

/**
 * Create token highlight decoration for Python code
 */
function createPythonLineHighlight(
  doc: { lines: number; line: (n: number) => { from: number; to: number; text: string } },
  highlight: PythonTokenHighlight | null
): DecorationSet {
  if (highlight === null || highlight.line < 1) {
    return Decoration.none
  }

  if (highlight.line > doc.lines) {
    return Decoration.none
  }

  const builder = new RangeSetBuilder<Decoration>()
  const line = doc.line(highlight.line)

  // Calculate token position
  const tokenStart = line.from + highlight.col
  const tokenEnd = Math.min(tokenStart + highlight.length, line.to)

  // Validate positions
  if (tokenStart < line.from || tokenStart > line.to || tokenEnd < tokenStart) {
    return Decoration.none
  }

  // Decorations must be added in sorted order by 'from' position, then by 'side' (for widgets)
  // Order: widget (side: -1) < marks (no side, treated as 0)
  
  // 1. Add gutter marker first (widget with side: -1, comes before all marks)
  builder.add(
    line.from,
    line.from,
    Decoration.widget({
      widget: new PythonLineMarkerWidget(),
      side: -1
    })
  )

  // 2. Add decorations in order: when marks start at same position, add shorter one first
  // This ensures proper ordering for CodeMirror's RangeSetBuilder
  if (tokenStart === line.from) {
    // Token starts at line start - add token first (shorter), then line background (longer)
    builder.add(
      tokenStart,
      tokenEnd,
      Decoration.mark({
        class: 'cm-python-mapped-token'
      })
    )
    builder.add(
      line.from,
      line.to,
      Decoration.mark({
        class: 'cm-python-mapped-line-bg'
      })
    )
  } else {
    // Token starts after line start - add line background first, then token
    builder.add(
      line.from,
      line.to,
      Decoration.mark({
        class: 'cm-python-mapped-line-bg'
      })
    )
    builder.add(
      tokenStart,
      tokenEnd,
      Decoration.mark({
        class: 'cm-python-mapped-token'
      })
    )
  }

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
      background: linear-gradient(to right, #0366d6, transparent);
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
        decorations = createPythonLineHighlight(tr.state.doc, effect.value)
      }
    }

    return decorations
  },
  provide: f => EditorView.decorations.from(f)
})

/**
 * Update Python token highlight
 */
export function updatePythonLineHighlight(
  view: EditorView,
  highlight: PythonTokenHighlight | null
) {
  // The effect will be handled by the state field's update method
  view.dispatch({
    effects: updatePythonLineEffect.of(highlight)
  })
}

/**
 * State effect to update unmapped code regions
 */
export const updateUnmappedCodeEffect = StateEffect.define<UnmappedCodeRegion[]>()

/**
 * State field for storing unmapped code regions
 */
export const unmappedCodeStateField = StateField.define<UnmappedCodeRegion[]>({
  create() {
    return []
  },
  update(regions, tr) {
    for (const effect of tr.effects) {
      if (effect.is(updateUnmappedCodeEffect)) {
        return effect.value
      }
    }
    return regions
  }
})

/**
 * Create decorations for unmapped code regions (with reduced opacity)
 */
function createUnmappedCodeDecorations(
  doc: { lines: number; line: (n: number) => { from: number; to: number; text: string } },
  regions: UnmappedCodeRegion[]
): DecorationSet {
  if (!regions || regions.length === 0) {
    return Decoration.none
  }

  const builder = new RangeSetBuilder<Decoration>()

  for (const region of regions) {
    // Skip invalid regions
    if (region.line < 1 || region.line > doc.lines) {
      continue
    }

    const line = doc.line(region.line)
    
    // Calculate position
    const from = line.from + region.col
    const to = Math.min(from + region.length, line.to)

    // Validate positions
    if (from < line.from || from > line.to || to < from) {
      continue
    }

    // Add decoration with reduced opacity
    builder.add(
      from,
      to,
      Decoration.mark({
        class: 'cm-unmapped-code',
        attributes: {
          'data-unmapped-line': String(region.line),
          'data-unmapped-col': String(region.col)
        }
      })
    )
  }

  return builder.finish()
}

/**
 * State field for unmapped code decorations
 */
export const unmappedCodeDecorationsField = StateField.define<DecorationSet>({
  create() {
    return Decoration.none
  },
  update(decorations, tr) {
    decorations = decorations.map(tr.changes)

    for (const effect of tr.effects) {
      if (effect.is(updateUnmappedCodeEffect)) {
        const regions = effect.is(updateUnmappedCodeEffect)
          ? effect.value
          : tr.state.field(unmappedCodeStateField)
        decorations = createUnmappedCodeDecorations(tr.state.doc, regions)
      }
    }

    return decorations
  },
  provide: f => EditorView.decorations.from(f)
})

/**
 * Update unmapped code regions
 */
export function updateUnmappedCodeRegions(
  view: EditorView,
  regions: UnmappedCodeRegion[]
) {
  view.dispatch({
    effects: updateUnmappedCodeEffect.of(regions)
  })
}

// ============================================================================
// Changed Lines Gutter Decorations (Green bar for new/modified lines)
// ============================================================================

/**
 * State field for tracking changed lines
 */
export const changedLinesStateField = StateField.define<number[]>({
  create() {
    return []
  },
  update(lines, tr) {
    for (const effect of tr.effects) {
      if (effect.is(updateChangedLinesEffect)) {
        return effect.value
      }
    }
    return lines
  }
})

/**
 * Gutter marker for changed lines (green bar)
 */
class ChangedLineMarker extends GutterMarker {
  toDOM() {
    const marker = document.createElement('div')
    marker.style.width = '3px'
    marker.style.height = '100%'
    marker.style.backgroundColor = '#22c55e'  // Green color
    marker.style.marginLeft = '-3px'
    marker.title = 'Modified or added line'
    return marker
  }
}

const changedLineMarker = new ChangedLineMarker()

/**
 * Gutter extension for showing changed lines
 */
export const changedLinesGutter = gutter({
  class: 'cm-changed-lines-gutter',
  markers: view => {
    const changedLines = view.state.field(changedLinesStateField)
    const builder = new RangeSetBuilder<GutterMarker>()
    
    for (const lineNum of changedLines) {
      if (lineNum > 0 && lineNum <= view.state.doc.lines) {
        const line = view.state.doc.line(lineNum)
        builder.add(line.from, line.from, changedLineMarker)
      }
    }
    
    return builder.finish()
  }
})

/**
 * Update changed lines
 */
export function updateChangedLines(
  view: EditorView,
  changedLines: number[]
) {
  view.dispatch({
    effects: updateChangedLinesEffect.of(changedLines)
  })
}
