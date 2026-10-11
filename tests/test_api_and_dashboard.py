
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

def test_api_initialization():
    try:
        from src.api.app import app
        assert app is not None
        print("API application imported successfully.")
    except Exception as e:
        print(f"Failed to import/initialize FastAPI app: {e}")
        sys.exit(1)

def test_dashboard_compilation():
    dashboard_path = project_root / "dashboard.py"
    assert dashboard_path.exists()
    import py_compile
    try:
        py_compile.compile(str(dashboard_path), doraise=True)
        print("Dashboard syntax compilation successful.")
    except Exception as e:
        print(f"Dashboard syntax error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_api_initialization()
    test_dashboard_compilation()
    print("Verification completed successfully.")
