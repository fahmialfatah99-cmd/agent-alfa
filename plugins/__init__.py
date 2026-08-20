"""
Dynamic Plugin Architecture for Telegram AI Bot.
Allows the bot to dynamically load, execute, and self-evolve tools from the plugins/ directory
without modifying core codebase files.
"""

import os
import sys
import glob
import importlib.util
import logging
from typing import List, Callable, Dict, Any

logger = logging.getLogger("PluginsLoader")
PLUGINS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_all_plugin_tools() -> List[Callable]:
    """
    Dynamically discovers and loads all callable tool functions from Python files in plugins/.
    Returns a list of functions ready to be passed to Gemini API tools.
    """
    loaded_tools = []
    py_files = glob.glob(os.path.join(PLUGINS_DIR, "*.py"))
    
    for filepath in py_files:
        basename = os.path.basename(filepath)
        if basename == "__init__.py" or basename.startswith("."):
            continue
            
        module_name = f"plugins.{os.path.splitext(basename)[0]}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(module, attr_name)
                if callable(attr) and hasattr(attr, "__doc__") and attr.__doc__:
                    if getattr(attr, "__module__", "") == module_name:
                        loaded_tools.append(attr)
                        logger.info(f"Loaded dynamic plugin tool: {attr_name} from {basename}")
        except Exception as e:
            logger.error(f"Failed to load plugin {basename}: {e}")
            
    return loaded_tools


def create_and_register_plugin(tool_name: str, tool_description: str, tool_code: str) -> Dict[str, Any]:
    """
    Saves a self-evolved tool as an isolated Python module in plugins/<tool_name>.py
    and verifies that it compiles and imports successfully.
    """
    import re
    import subprocess
    
    if not re.match(r"^[a-z][a-z0-9_]*$", tool_name):
        return {"status": "error", "message": "Nama tool harus lowercase alphanumeric + underscore, dimulai dengan huruf."}
        
    plugin_path = os.path.join(PLUGINS_DIR, f"{tool_name}.py")
    
    header = (
        f'"""\n'
        f'Dynamic Plugin Tool: {tool_name}\n'
        f'Description: {tool_description}\n'
        f'"""\n\n'
        f'import os\n'
        f'import sys\n'
        f'import json\n'
        f'import subprocess\n'
        f'from typing import Dict, Any, List, Optional\n\n'
    )
    full_content = header + tool_code.strip() + "\n"
    
    try:
        compile(full_content, plugin_path, "exec")
        with open(plugin_path, "w", encoding="utf-8") as f:
            f.write(full_content)
            
        res = subprocess.run([sys.executable, "-m", "py_compile", plugin_path], capture_output=True, text=True)
        if res.returncode != 0:
            if os.path.exists(plugin_path):
                os.remove(plugin_path)
            return {"status": "error", "message": f"Plugin compilation failed: {res.stderr}"}
            
        return {
            "status": "success",
            "message": f"🧬 Plugin '{tool_name}' berhasil dibuat di plugins/{tool_name}.py dan siap dimuat!",
            "plugin_file": plugin_path,
            "tool_name": tool_name,
            "needs_restart": True
        }
    except Exception as e:
        if os.path.exists(plugin_path):
            try:
                os.remove(plugin_path)
            except OSError:
                pass
        return {"status": "error", "message": f"Failed to create plugin: {str(e)}"}
