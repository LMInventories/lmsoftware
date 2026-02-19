import sys
import os

print("Python path:", sys.path)
print("Current directory:", os.getcwd())
print("\n--- Checking files ---")

# Check if app folder exists
if os.path.exists('app'):
    print("✓ app/ folder exists")
    
    # Check for __init__.py
    if os.path.exists('app/__init__.py'):
        print("✓ app/__init__.py exists")
        file_size = os.path.getsize('app/__init__.py')
        print(f"  File size: {file_size} bytes")
        if file_size == 0:
            print("  WARNING: File is empty!")
    else:
        print("✗ app/__init__.py MISSING!")
    
    # Check for models.py
    if os.path.exists('app/models.py'):
        print("✓ app/models.py exists")
    else:
        print("✗ app/models.py MISSING!")
else:
    print("✗ app/ folder MISSING!")

# Check for config.py
if os.path.exists('config.py'):
    print("✓ config.py exists")
else:
    print("✗ config.py MISSING!")

print("\n--- Attempting import ---")
try:
    from app import create_app
    print("✓ SUCCESS! create_app imported")
except Exception as e:
    print("✗ ERROR:", str(e))
    import traceback
    traceback.print_exc()
