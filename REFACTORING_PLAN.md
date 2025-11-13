# Codebase Refactoring Plan

## Current State Analysis

### Issues Identified:
1. **Two competing architectures**: MVP (working) vs IR-based (broken)
2. **Legacy files**: parser.py, generator.py, sync.py (superseded)
3. **Broken files**: main.py, robust_sync.py, robust_mapper.py, node_classifier.py, edit_dispatcher.py (missing imports)
4. **~40% duplicate functionality** across modules
5. **Poor modularization**: Edit operations scattered across 4 files
6. **Inconsistent naming**: mvp_ prefix on some, not others

### Metrics:
- **Total files**: 20 Python files
- **Working files**: 11 (MVP architecture)
- **Broken files**: 5 (missing imports)
- **Legacy files**: 4 (superseded)
- **Lines of code**: ~8,000+
- **Recommended cleanup**: Remove 9 files (~3,500 lines)

---

## Refactoring Strategy

### Phase 1: Archive & Remove (High Priority)
**Goal**: Clean up dead code, reduce confusion

1. **Archive broken IR-based files** → `backend/archived/ir_architecture/`
   - main.py (broken imports)
   - robust_sync.py (broken imports)
   - robust_mapper.py (broken imports)
   - node_classifier.py (broken imports)
   - edit_dispatcher.py (broken imports)
   - mapping_types.py (used by broken files only)

2. **Delete legacy duplicate files**
   - parser.py (superseded by mvp_parser.py)
   - generator.py (superseded by mvp_generator.py)
   - sync.py (superseded by robust_sync.py, both now archived)

**Impact**: -9 files, ~-3,500 lines, zero broken imports

---

### Phase 2: Consolidate & Modularize (High Priority)
**Goal**: Clean architecture with clear boundaries

3. **Consolidate edit operations**
   ```
   Current scattered across:
   - mvp_edit.py (direct AST ops)
   - mvp_translator.py (edit routing)
   - mvp_smart_editor.py (coordination)

   Refactor to:
   - edit_operations.py (low-level AST manipulation)
   - edit_router.py (type classification & routing decision)
   - edit_coordinator.py (high-level orchestration)
   ```

4. **Unify mapping systems**
   ```
   Current split:
   - mvp_tree_mapper.py (tree-based similarity)
   - robust_mapper.py (node classification, archived)
   - Mapping embedded in mvp_generator.py

   Refactor to:
   - mapper.py (unified mapping with tree similarity)
   - Keep mapping types in generator where they're used
   ```

---

### Phase 3: Naming & Organization (Medium Priority)
**Goal**: Consistent, semantic naming

5. **Remove mvp_ prefix**
   ```
   mvp_main.py         → main.py
   mvp_parser.py       → parser.py
   mvp_generator.py    → generator.py
   mvp_editor.py       → editor.py
   mvp_translator.py   → (merged into edit_router.py)
   mvp_smart_editor.py → (merged into edit_coordinator.py)
   mvp_edit.py         → edit_operations.py
   mvp_tree_mapper.py  → mapper.py
   mvp_config.py       → config.py
   mvp_implementation_generator.py → implementation_generator.py
   ```

6. **Standardize configuration**
   - Extend config.py to cover all modules
   - Remove hardcoded values from other files
   - Single source of truth for settings

---

### Phase 4: Module Organization (Low Priority, Future)
**Goal**: Logical directory structure

7. **Reorganize into functional subdirectories**
   ```
   backend/
   ├── api/
   │   └── main.py              # FastAPI endpoints
   ├── core/
   │   ├── editor.py            # Main orchestrator
   │   ├── parser.py            # Semiformal parsing
   │   └── generator.py         # Code generation
   ├── editing/
   │   ├── operations.py        # Low-level AST ops
   │   ├── router.py            # Edit routing
   │   └── coordinator.py       # High-level coordination
   ├── mapping/
   │   ├── mapper.py            # Bidirectional mapping
   │   └── implementation_generator.py
   ├── utils/
   │   └── config.py            # Configuration
   └── archived/
       └── ir_architecture/     # Broken IR files
   ```

---

## Implementation Steps

### Step 1: Archive broken IR architecture
```bash
mkdir -p backend/archived/ir_architecture
git mv backend/main.py backend/archived/ir_architecture/
git mv backend/robust_sync.py backend/archived/ir_architecture/
git mv backend/robust_mapper.py backend/archived/ir_architecture/
git mv backend/node_classifier.py backend/archived/ir_architecture/
git mv backend/edit_dispatcher.py backend/archived/ir_architecture/
git mv backend/mapping_types.py backend/archived/ir_architecture/
```

### Step 2: Remove legacy files
```bash
git rm backend/parser.py
git rm backend/generator.py
git rm backend/sync.py
```

### Step 3: Rename MVP files (remove prefix)
```bash
git mv backend/mvp_main.py backend/main.py
git mv backend/mvp_parser.py backend/parser.py
git mv backend/mvp_generator.py backend/generator.py
git mv backend/mvp_editor.py backend/editor.py
git mv backend/mvp_config.py backend/config.py
git mv backend/mvp_tree_mapper.py backend/mapper.py
git mv backend/mvp_implementation_generator.py backend/implementation_generator.py
```

### Step 4: Consolidate edit operations
- Merge mvp_edit.py → edit_operations.py
- Merge mvp_translator.py + routing logic → edit_router.py
- Merge mvp_smart_editor.py + coordination → edit_coordinator.py

### Step 5: Update all imports
- Search and replace imports across all files
- Update __init__.py if needed
- Test that everything still works

---

## Expected Outcomes

### Quantitative:
- **Files reduced**: 20 → 11 (-45%)
- **Lines of code**: ~8,000 → ~6,500 (-19%)
- **Duplicate code**: 40% → ~10%
- **Broken imports**: 6 → 0
- **Clear architecture**: 1 (MVP only)

### Qualitative:
- ✅ Single coherent architecture
- ✅ Clear module boundaries
- ✅ Consistent naming
- ✅ Zero broken imports
- ✅ Reduced cognitive load
- ✅ Easier maintenance
- ✅ Better for onboarding

---

## Testing Strategy

After each phase:
1. Run existing tests
2. Check imports resolve correctly
3. Start server and test endpoints
4. Verify no regressions

---

## Rollback Plan

If issues arise:
1. All changes are in git
2. Can revert specific commits
3. Archived files preserved, can be restored

---

## Timeline

- **Phase 1** (Archive & Remove): 30 minutes
- **Phase 2** (Consolidate): 1-2 hours
- **Phase 3** (Rename): 30 minutes
- **Phase 4** (Reorganize): Future work

**Total for Phases 1-3**: ~3 hours
