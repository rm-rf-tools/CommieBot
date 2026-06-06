import os
import re
import json
import ast

def get_method_name(node):
    """Safely extract the method name from an AST Call node."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    elif isinstance(node.func, ast.Name):
        return node.func.id
    return None

def extract_bot_replies():
    botreplies = {}
    
    # The base method calls we are targeting across the codebase
    target_methods = {
        'edit_original_response', 
        'send_message', 
        'send', 
        'reply'
    }
    
    for root, _, files in os.walk('.'):
        # Ignore virtual environments, git configs, and pycache
        if any(x in root for x in ['venv', '.git', '__pycache__']):
            continue
            
        for file in files:
            if file.endswith('.py') and file != os.path.basename(__file__):
                filepath = os.path.join(root, file)
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    source = f.read()
                    
                try:
                    tree = ast.parse(source, filename=filepath)
                except SyntaxError:
                    continue
                    
                filename = os.path.basename(file)
                
                # Walk the Abstract Syntax Tree looking for function calls
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        method_name = get_method_name(node)
                        if method_name in target_methods:
                            msg_clean = None
                            
                            # 1. Check keyword arguments for 'content='
                            for kw in node.keywords:
                                if kw.arg == 'content':
                                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                        msg_clean = kw.value.value
                                    elif isinstance(kw.value, ast.JoinedStr):
                                        raw_str = ast.unparse(kw.value)
                                        msg_clean = clean_f_string(raw_str)
                                    break
                            
                            # 2. If no content kwarg, check the first positional argument
                            if msg_clean is None and node.args:
                                first_arg = node.args[0]
                                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                                    msg_clean = first_arg.value
                                elif isinstance(first_arg, ast.JoinedStr):
                                    raw_str = ast.unparse(first_arg)
                                    msg_clean = clean_f_string(raw_str)
                                    
                            if msg_clean is not None:
                                # Ignore empty strings (usually just sending embeds without content)
                                if not str(msg_clean).strip():
                                    continue

                                if filename not in botreplies:
                                    botreplies[filename] = {}
                                if method_name not in botreplies[filename]:
                                    botreplies[filename][method_name] = {}
                                
                                # Generate deterministic key: Alphanumeric, max 20 chars, uppercase
                                key_base = re.sub(r'[^A-Za-z0-9]', '', str(msg_clean)).upper()
                                key = key_base[:20] if key_base else "EMPTYMSG"
                                
                                # Handle exact duplicate keys in the same method/file logically
                                original_key = key
                                counter = 1
                                while key in botreplies[filename][method_name] and botreplies[filename][method_name][key] != msg_clean:
                                    key = f"{original_key}_{counter}"
                                    counter += 1
                                    
                                botreplies[filename][method_name][key] = msg_clean

    # Write dictionary to JSON file
    os.makedirs('text', exist_ok=True)
    with open('text/botreplies.json', 'w', encoding='utf-8') as f:
        json.dump(botreplies, f, indent=4, ensure_ascii=False)
        
    print(f"✅ Successfully extracted {sum(len(methods) for file in botreplies.values() for methods in file.values())} keys to text/botreplies.json")

def clean_f_string(raw_str: str) -> str:
    """Removes the surrounding f and quotes from an unparsed AST JoinedStr."""
    if raw_str.startswith("f'''") or raw_str.startswith('f"""'):
        return raw_str[4:-3]
    elif raw_str.startswith("f'") or raw_str.startswith('f"'):
        return raw_str[2:-1]
    return raw_str

if __name__ == "__main__":
    extract_bot_replies()