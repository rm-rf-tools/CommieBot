import json
import re
import os

def main():
    json_path = os.path.join("static", "text", "botreplies.json")
    
    if not os.path.exists(json_path):
        print(f"❌ Could not find {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    guide_lines = ["=== COPY/PASTE REFACTOR GUIDE ===\nReplace the hardcoded strings in your cogs with the code below:\n"]

    for file_name, methods in data.items():
        for method, keys in methods.items():
            for key, msg in keys.items():
                
                # Match {expression} or {expression:format_specifier}
                matches = re.finditer(r'\{([^:}]+)(:[^}]+)?\}', msg)
                
                new_msg = msg
                format_kwargs = []
                has_variables = False
                
                for match in matches:
                    has_variables = True
                    expr = match.group(1).strip()
                    fmt = match.group(2) or ""
                    
                    # Generate a safe variable name by stripping symbols
                    safe_var = re.sub(r'[^a-zA-Z0-9_]', '_', expr).strip('_')
                    safe_var = re.sub(r'_+', '_', safe_var) # Collapse multiple underscores
                    
                    # Replace the complex expression in the string with the safe variable
                    new_msg = new_msg.replace(match.group(0), f"{{{safe_var}{fmt}}}")
                    
                    # Map the safe variable to the original Python logic for the .format() call
                    format_kwargs.append(f"{safe_var}={expr}")
                
                if has_variables:
                    # Update JSON dictionary with the safe template
                    data[file_name][method][key] = new_msg
                    
                    # Build the copy-paste Python code
                    kwargs_str = ", ".join(format_kwargs)
                    guide_lines.append(f"File: cogs/{file_name}")
                    guide_lines.append(f"Key:  {key}")
                    guide_lines.append(f"Code: DatabaseController.botreplies[\"{file_name}\"][\"{method}\"][\"{key}\"].format({kwargs_str})")
                    guide_lines.append("-" * 60)

    # 1. Overwrite the JSON with the fixed, safe templates
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    # 2. Output the refactor guide
    with open("refactor_guide.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(guide_lines))

    print(f"✅ Fixed botreplies.json! Open 'refactor_guide.txt' to see exactly how to update your Python code.")

if __name__ == "__main__":
    main()