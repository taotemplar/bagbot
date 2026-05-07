import ast
from pathlib import Path
import sys
from types import SimpleNamespace

class InvalidSettings(Exception): pass

def load_safe_python_settings():
    settings = {}

    # Determine where to look for the files (works in dev and when frozen with PyInstaller/Nuitka)
    exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(".")

    default_path = exe_dir / "bagbot_settings.py"
    overrides_path = exe_dir / "bagbot_settings_overrides.py"

    for path in [default_path, overrides_path]:
        is_default = (path == default_path)

        if not path.exists():
            if is_default:
                raise FileNotFoundError(f"CRITICAL: {path} is missing! Cannot continue.")
            else:
                print(f"Info: Optional overrides file not found (this is fine): {path}")
                continue  # overrides are optional

        source = path.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source)  # mode='exec' by default → accepts real Python files
        except SyntaxError as e:
            raise SyntaxError(f"Invalid Python syntax in {path.name}: {e}") from e

        for node in tree.body:
            # Simple assignment: VAR = value
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id.isidentifier():
                    name = target.id
                    try:
                        value = ast.literal_eval(node.value)
                        settings[name] = value
                    except (ValueError, SyntaxError):
                        print(f"Warning: Skipping unsafe or invalid value for '{name}' in {path.name}")

            # Allow top-level comments / docstrings / pass etc. → just ignore them
            # (optional) you can also support AnnAssign (typed vars) if you want:
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
                if node.value:  # only if there's actually a value
                    try:
                        value = ast.literal_eval(node.value)
                        settings[name] = value
                    except (ValueError, SyntaxError):
                        print(f"Warning: Skipping unsafe annotated assignment '{name}' in {path.name}")

    return SimpleNamespace(**settings)

bagbot_settings = load_safe_python_settings()