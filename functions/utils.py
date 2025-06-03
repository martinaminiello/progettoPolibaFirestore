import uuid
import datetime

#convert tree keys to be compatible with firestore
def convert_tree_keys(tree_section):
    if isinstance(tree_section, dict):
        new_tree = {}
        for key, value in tree_section.items():
            # Se è un file (dopo split_tree: valore stringa vuota)
            if value == "":
                new_key = key[::-1].replace("_", ".", 1)[::-1]
            # Se è un file (prima di split_tree: dict con content e last-modifier)
            elif (
                isinstance(value, dict)
                and "content" in value
                and "last-modifier" in value
            ):
                new_key = key[::-1].replace("_", ".", 1)[::-1]
            else:
                new_key = key
            new_tree[new_key] = convert_tree_keys(value)
        return new_tree
    elif isinstance(tree_section, list):
        return [convert_tree_keys(item) for item in tree_section]
    else:
        return tree_section
    

def split_tree(tree, base_path=""):
    tree_structure = {}
    file_info_dict = {}

    for key, value in tree.items():
        current_path = f"{base_path}/{key}" if base_path else key
        if isinstance(value, dict):
            # If it's a file dict (has 'content' and 'last-modifier'), add it as a file
            if "content" in value and "last-modifier" in value:
                tree_structure[key] = ""
                file_info_dict[current_path] = {
                    "content": value.get("content", ""),
                    "last-modifier": value.get("last-modifier", "")
                }
            else:
                # Otherwise, it's a folder, recurse
                sub_tree, sub_files = split_tree(value, current_path)
                tree_structure[key] = sub_tree
                file_info_dict.update(sub_files)
        elif isinstance(value, list):
            tree_structure[key] = ""
            for entry in value:
                file_info_dict[current_path] = {
                    "content": entry.get("content", ""),
                    "last-modifier": entry.get("last-modifier", "")
                }
        else:
            pass

    return tree_structure, file_info_dict
    
def insert_last_modified(file_info_dict):
    last_modified_dict = {}
    for filepath, info in file_info_dict.items():
     
        uuid_cache = str(uuid.uuid4())
        timestamp = datetime.datetime.now(datetime.timezone.utc)
        last_modified_dict[filepath] = {
            "content": info.get("content"),
            "uuid_cache": uuid_cache,
            "last-modifier": info.get("last-modifier"),
            "timestamp": timestamp
        }
    return {"last-modified": last_modified_dict}




