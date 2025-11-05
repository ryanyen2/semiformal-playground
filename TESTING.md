# Testing Guide for Semiformal Programming Playground

This guide will help you test the bidirectional programming features.

## Setup for Testing

1. Make sure both backend and frontend are running:
   ```bash
   # Terminal 1
   ./start-backend.sh

   # Terminal 2
   ./start-frontend.sh
   ```

2. Open http://localhost:3000 in your browser

## Test Cases

### Test 1: Basic Parsing and Stub Generation

**Goal**: Verify the parser identifies incomplete code and creates stubs.

**Steps**:
1. Clear the spec editor and write:
   ```python
   result = process_data(raw_input)
   print(result)
   ```

2. Click "Parse"

**Expected Result**:
- The code should be annotated with a stub:
  ```python
  def process_data(arg0):
      ...

  result = process_data(raw_input)
  print(result)
  ```
- Status bar shows: "Parsed: X incomplete parts, Y stubs created"

### Test 2: LLM Code Generation

**Goal**: Verify LLM generates complete code from semiformal spec.

**Steps**:
1. Use the parsed code from Test 1
2. Click "Generate Code"

**Expected Result**:
- Right editor shows complete Python code with `process_data` implemented
- Status bar shows: "Generated code with X completions"

**Note**: Requires valid OPENAI_API_KEY in .env file

### Test 3: Natural Language Variables

**Goal**: Test natural language to code conversion.

**Steps**:
1. Write in spec editor:
   ```python
   x = split dataset into training and test sets
   print(x)
   ```

2. Click "Parse" then "Generate Code"

**Expected Result**:
- Parser marks the NL text with grayed out styling (opacity 0.5)
- Generated code converts NL to Python expression:
  ```python
  x = train_test_split(dataset)  # or similar
  print(x)
  ```

### Test 4: Spec → Code Sync (Parameter Addition)

**Goal**: Test automatic sync when adding parameters.

**Steps**:
1. Generate code from a simple function:
   ```python
   def transform(data):
       ...

   result = transform(my_data)
   ```

2. After generation, edit the spec to add a parameter:
   ```python
   def transform(data, normalize):
       ...
   ```

3. Blur the editor (click outside or tab away)

**Expected Result**:
- Generated code automatically updates with new parameter
- Function body regenerates to use the parameter
- Status bar shows: "Synced add_param to code"

### Test 5: Spec → Code Sync (Function Rename)

**Goal**: Test function rename propagation.

**Steps**:
1. Start with generated code that has a function
2. In the spec, rename the function:
   ```python
   def process_data(x):  # was: transform
       ...
   ```

3. Blur the editor

**Expected Result**:
- Function name updates in generated code
- All function calls update to use new name
- No LLM regeneration (pure rename)
- Status bar shows: "Synced rename_func to code"

### Test 6: Spec → Code Sync (Statement Insertion)

**Goal**: Test dependency-aware statement insertion.

**Steps**:
1. Have a generated function with variable `a`:
   ```python
   def process():
       a = 10
       b = a + 5
       return b
   ```

2. In spec, add to the stub:
   ```python
   def process():
       print(a)  # Add this line
   ```

3. Blur the editor

**Expected Result**:
- `print(a)` inserted after last assignment to `a` in generated code
- Status bar shows: "Synced insert_statement to code"

### Test 7: Code → Spec Sync

**Goal**: Test surfacing code edits back to spec.

**Steps**:
1. Generate code from a spec
2. Edit a line in the generated code
3. Click "Sync to Spec"

**Expected Result**:
- Edited line appears in the corresponding function stub in spec
- Status bar shows: "Synced code changes to spec"

### Test 8: Incomplete Code with Ellipsis

**Goal**: Test variables assigned to `...`

**Steps**:
1. Write in spec:
   ```python
   x = ...
   y = x + 10
   print(y)
   ```

2. Parse and generate

**Expected Result**:
- Parser identifies `x` as incomplete
- Generated code provides a concrete value for `x`

### Test 9: Multiple Incomplete Parts

**Goal**: Test handling multiple incomplete elements.

**Steps**:
1. Write complex semiformal code:
   ```python
   data = load dataset from file
   processed = preprocess(data)
   result = analyze(processed)

   def preprocess(d):
       ...

   print(result)
   ```

2. Parse and generate

**Expected Result**:
- All incomplete parts identified
- Stubs created for missing functions
- NL text converted to code
- All functions properly implemented

### Test 10: Error Handling

**Goal**: Verify graceful error handling.

**Steps**:
1. Try generating without OPENAI_API_KEY set
2. Try parsing invalid Python syntax
3. Try syncing with malformed edits

**Expected Result**:
- Appropriate error messages in status bar
- Application doesn't crash
- User can recover and continue

## API Testing

You can also test the backend API directly:

```bash
# Health check
curl http://localhost:8000/

# Parse code
curl -X POST http://localhost:8000/parse \
  -H "Content-Type: application/json" \
  -d '{"code": "result = foo(x)\nprint(result)"}'

# Generate code (requires API key)
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"semiformal_code": "result = foo(x)\nprint(result)"}'
```

## Troubleshooting

### Backend Issues

- **Port 8000 already in use**: Another process is using the port
  ```bash
  lsof -ti:8000 | xargs kill -9
  ```

- **Module not found**: Virtual environment not activated or dependencies not installed
  ```bash
  source venv/bin/activate
  pip install -r requirements.txt
  ```

- **OpenAI API errors**: Check .env file has valid OPENAI_API_KEY

### Frontend Issues

- **Port 3000 already in use**: Change port in vite.config.ts

- **Connection refused**: Backend not running or CORS issues

- **TypeScript errors**: Try `npm install` again

## Performance Testing

For performance evaluation:

1. **Parsing Speed**: Should handle files up to 1000 lines quickly
2. **Generation Speed**: Depends on OpenAI API (typically 2-5 seconds)
3. **Sync Speed**: Should be near-instant for non-LLM operations

## UI/UX Testing

Check that:
- [ ] Code decorations appear correctly (grayed out NL text, highlighted stubs)
- [ ] Status bar messages are clear and helpful
- [ ] Both editors are editable and responsive
- [ ] Buttons are appropriately enabled/disabled
- [ ] Layout is responsive and usable

## Known Limitations

1. **Complex AST Parsing**: Very complex Python may not parse correctly
2. **LLM Hallucinations**: Generated code may not always be perfect
3. **Dependency Detection**: Simple regex-based, may miss complex dependencies
4. **Multi-line Edits**: Only handles simple edit patterns
5. **Error Recovery**: May need manual intervention for some edge cases

## Reporting Issues

When reporting issues, please include:
- Steps to reproduce
- Expected vs actual behavior
- Browser console output (F12)
- Backend logs
- Code samples that trigger the issue
