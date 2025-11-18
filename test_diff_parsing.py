#!/usr/bin/env python3
"""
Test diff parsing and application with real examples.
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from postprocessing import CodePostprocessor


def test_example_diff():
    """Test with the exact example from the user's issue"""
    
    print("\n=== Test: User's Example Diff ===\n")
    
    existing_code = """import pandas as pd

from sklearn.model_selection import train_test_split

def load_and_process_dataset(file_path):  #> load; dataset; process it
    data = pd.read_csv(file_path)
    processed_data = data.dropna()
    return processed_data

def transform(data):  #> transform
    return data.apply(lambda x: x * 2)

result = load_and_process_dataset('data.csv')  #> result; load; dataset; process it

output = transform(result)  #> output; transform; result

x, y = train_test_split(result, test_size=0.2, random_state=42)  #> x; y; split data into train and test

print(output)  #> print; output
"""

    diff_output = """```diff
--- a/code.py
+++ b/code.py
@@ -1,11 +1,14 @@
 import pandas as pd
 from sklearn.model_selection import train_test_split
 
-def load_and_process_dataset(file_path):  #> load; dataset; process it
-    data = pd.read_csv(file_path)
+def load_and_process_iris_dataset():  #> load; iris dataset; process it
+    from sklearn.datasets import load_iris
+    iris = load_iris(as_frame=True)
+    data = iris.frame
     processed_data = data.dropna()
     return processed_data
 
-result = load_and_process_dataset('data.csv')  #> result; load; dataset; process it
+result = load_and_process_iris_dataset()  #> result; load; iris dataset; process it
 
 
 output = transform(result)  #> output; transform; result
```"""

    postprocessor = CodePostprocessor()
    result = postprocessor.apply_diff_patch(existing_code, diff_output)
    
    print("Original code:")
    print(existing_code)
    print("\n" + "="*60 + "\n")
    print("Diff to apply:")
    print(diff_output)
    print("\n" + "="*60 + "\n")
    print("Result after applying diff:")
    print(result)
    print("\n" + "="*60 + "\n")
    
    # Expected result should have:
    expected_lines = [
        "import pandas as pd",
        "from sklearn.model_selection import train_test_split",
        "",
        "def load_and_process_iris_dataset():  #> load; iris dataset; process it",
        "    from sklearn.datasets import load_iris",
        "    iris = load_iris(as_frame=True)",
        "    data = iris.frame",
        "    processed_data = data.dropna()",
        "    return processed_data",
        "",
        "def transform(data):  #> transform",
        "    return data.apply(lambda x: x * 2)",
        "",
        "result = load_and_process_iris_dataset()  #> result; load; iris dataset; process it",
        "",
        "output = transform(result)  #> output; transform; result",
        "",
        "x, y = train_test_split(result, test_size=0.2, random_state=42)  #> x; y; split data into train and test",
        "",
        "print(output)  #> print; output"
    ]
    
    result_lines = result.split('\n')
    
    # Check key changes
    assert "load_and_process_iris_dataset" in result, "Function name should be changed"
    assert "load_and_process_dataset" not in result or "load_and_process_dataset('data.csv')" not in result, "Old function call should be removed"
    assert "from sklearn.datasets import load_iris" in result, "Should add sklearn.datasets import"
    assert "iris = load_iris(as_frame=True)" in result, "Should add iris loading"
    assert "data = iris.frame" in result, "Should change data source"
    assert "def transform(data)" in result, "transform function should be preserved"
    assert "x, y = train_test_split" in result, "train_test_split should be preserved"
    
    print("✅ All assertions passed!")
    return result


def test_simple_diff():
    """Test a simple single-line change"""
    
    print("\n=== Test: Simple Single-Line Change ===\n")
    
    existing_code = """x = 1
y = 2
z = 3
"""

    diff_output = """```diff
--- a/code.py
+++ b/code.py
@@ -1,3 +1,3 @@
 x = 1
-y = 2
+y = 20
 z = 3
```"""

    postprocessor = CodePostprocessor()
    result = postprocessor.apply_diff_patch(existing_code, diff_output)
    
    print("Original:")
    print(repr(existing_code))
    print("\nDiff:")
    print(diff_output)
    print("\nResult:")
    print(repr(result))
    
    assert "y = 20" in result, "Should change y to 20"
    assert result.count("y = 2") == 0 or "y = 2\n" not in result, "Should not have old y = 2 as a complete line"
    assert "x = 1" in result, "Should preserve x = 1"
    assert "z = 3" in result, "Should preserve z = 3"
    
    print("✅ Simple diff test passed!")


def test_multiline_change():
    """Test adding multiple lines"""
    
    print("\n=== Test: Multiline Addition ===\n")
    
    existing_code = """def foo():
    return 1
"""

    diff_output = """```diff
--- a/code.py
+++ b/code.py
@@ -1,2 +1,5 @@
 def foo():
+    x = 10
+    y = 20
     return 1
```"""

    postprocessor = CodePostprocessor()
    result = postprocessor.apply_diff_patch(existing_code, diff_output)
    
    print("Original:")
    print(existing_code)
    print("\nResult:")
    print(result)
    
    assert "x = 10" in result, "Should add x = 10"
    assert "y = 20" in result, "Should add y = 20"
    assert "return 1" in result, "Should preserve return 1"
    
    print("✅ Multiline change test passed!")


def test_context_matching():
    """Test that context lines are properly matched"""
    
    print("\n=== Test: Context Matching ===\n")
    
    existing_code = """import os
import sys

def hello():
    print("hello")

def world():
    print("world")
"""

    diff_output = """```diff
--- a/code.py
+++ b/code.py
@@ -1,7 +1,7 @@
 import os
 import sys
 
-def hello():
+def hello_world():
     print("hello")
 
 def world():
```"""

    postprocessor = CodePostprocessor()
    result = postprocessor.apply_diff_patch(existing_code, diff_output)
    
    print("Original:")
    print(existing_code)
    print("\nResult:")
    print(result)
    
    assert "def hello_world():" in result, "Should rename function"
    assert "def hello():" not in result, "Should not have old function name"
    assert 'print("hello")' in result, "Should preserve print statement"
    assert "def world():" in result, "Should preserve world function"
    
    print("✅ Context matching test passed!")


if __name__ == "__main__":
    try:
        test_simple_diff()
        test_multiline_change()
        test_context_matching()
        result = test_example_diff()
        
        print("\n" + "="*60)
        print("🎉 ALL DIFF PARSING TESTS PASSED! 🎉")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

