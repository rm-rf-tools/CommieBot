import json
import os
import re

def main():
    json_path = os.path.join("static", "text", "botreplies.json")
    
    if not os.path.exists(json_path):
        print(f"❌ Could not find {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        botreplies = json.load(f)

    for filename, categories in botreplies.items():
        # Look for the target file in cogs/ or root directory
        filepath = os.path.join("cogs", filename)
        if not os.path.exists(filepath):
            filepath = filename
        if not os.path.exists(filepath):
            print(f"⚠️ Could not locate {filename} to modify.")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        replacements_made = 0

        for category, keys in categories.items():
            for key, msg in keys.items():
                
                # Detect formatting variables (e.g., {perms}, {role}) to append .format(perms=perms)
                variables = set(re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', msg))
                replacement = f'DatabaseController.botreplies["{filename}"]["{category}"]["{key}"]'
                
                if variables:
                    kwargs = ", ".join([f"{var}={var}" for var in variables])
                    replacement += f".format({kwargs})"

                # Possible ways the string could be wrapped in the source code
                possible_wrappers = [
                    ('f"""', '"""'), ("f'''", "'''"),
                    ('"""', '"""'), ("'''", "'''"),
                    ('f"', '"'), ("f'", "'"),
                    ('"', '"'), ("'", "'")
                ]
                
                # Pre-calculate escaped versions for standard quotes
                msg_escaped_double = msg.replace('"', '\\"')
                msg_escaped_single = msg.replace("'", "\\'")

                # Try to find and replace the string using the wrappers
                for prefix, suffix in possible_wrappers:
                    replaced = False
                    
                    # 1. Exact Match
                    target = f"{prefix}{msg}{suffix}"
                    if target in content:
                        content = content.replace(target, replacement)
                        replaced = True
                    
                    # 2. Match with Escaped Double Quotes
                    target_double = f"{prefix}{msg_escaped_double}{suffix}"
                    if not replaced and target_double in content:
                        content = content.replace(target_double, replacement)
                        replaced = True
                        
                    # 3. Match with Escaped Single Quotes
                    target_single = f"{prefix}{msg_escaped_single}{suffix}"
                    if not replaced and target_single in content:
                        content = content.replace(target_single, replacement)
                        replaced = True

                    if replaced:
                        replacements_made += 1
                        break # Stop looking for wrappers for this specific string once replaced

        if replacements_made > 0:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✅ Processed {filepath} - Replaced {replacements_made} strings.")
        else:
            print(f"⏩ Skipped {filepath} - No matching strings found to replace.")

if __name__ == "__main__":
    main()