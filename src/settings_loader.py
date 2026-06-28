import ast
from pathlib import Path
import sys
import os 
from types import SimpleNamespace
from dotenv import load_dotenv

class InvalidSettings(Exception): pass

def load_safe_python_settings():
    settings = {}

    # Determine where to look for the files
    exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(".")

    # Load .env file from the same dir as the settings file
    env_path = exe_dir / ".env"
    load_dotenv(env_path)

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

    namespace = SimpleNamespace(**settings)

    # Get wallet name & password from .env
    wallet_pw = os.environ.get("WALLET_PW")
    wallet_name = os.environ.get("WALLET_NAME")

    if wallet_pw is None:
        raise InvalidSettings("WALLET_PW is not set in the .env file")
    if wallet_name is None:
        raise InvalidSettings("WALLET_NAME is not set in the .env file")

    namespace.WALLET_PW = wallet_pw
    namespace.WALLET_NAME = wallet_name

    return SimpleNamespace(**settings)

bagbot_settings = load_safe_python_settings()
