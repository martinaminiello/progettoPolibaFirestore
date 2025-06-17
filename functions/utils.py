import uuid
import datetime
from firebase_admin import  firestore
from github import Github, Auth
from repomanager import Repository
from user import User


def initialized_repo():
    token = ""
    auth = Auth.Token(token)
    g = Github(auth=auth)
    print(f"User {g.get_user().login}")
    u = User(token)
    repository = Repository(u)
    return repository

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


def split_tree_with_name(realtime_tree, base_path=""):
    tree_structure = {}
    file_info_dict = {}

    for key, value in realtime_tree.items():
        if isinstance(value, dict):
            # It's a file
            if "content" in value and "last-modifier" in value and "_name" in value:
                full_path = f"{base_path}/{key}" if base_path else key
                tree_structure[key] = value["_name"]
                file_info_dict[full_path] = {
                    "content": value["content"],
                    "last-modifier": value["last-modifier"],
                    "_name": value["_name"]
                }
                print(f"[FILE] splittree path: {full_path}")
                print(f"  _name: {value['_name']}")
                print(f"  content: {value['content']}")
                print(f"  last-modifier: {value['last-modifier']}")
            
            # It's a directory
            elif "_name" in value:
                sub_tree, sub_files = split_tree_with_name(
                    value, f"{base_path}/{key}" if base_path else key
                )
                tree_structure[key] = {
                    "_name": value["_name"],
                    **sub_tree
                }
                file_info_dict.update(sub_files)

    return tree_structure, file_info_dict

def get_name_from_tree(path_parts, tree):
    node = tree
    names = []

    for part in path_parts:
        if isinstance(node, dict) and part in node:
            node = node[part]

            # node può essere dict (dir) o str (nome file), gestiamo entrambi
            if isinstance(node, dict):
                names.append(node.get("_name", part))
            else:
                names.append(node)  # è già il nome leggibile
        else:
            names.append(part)  # fallback
    return "/".join(names)



def convert_file_info_keys_to_readable(file_info_dict, tree_structure):
    readable_file_info = {}
    reverse_map = {}

    for internal_path, info in file_info_dict.items():
        parts = internal_path.strip("/").split("/")
        readable_path = get_name_from_tree(parts, tree_structure)

        readable_file_info[readable_path] = {
            "last-modifier": info["last-modifier"],
            "_name": info["_name"]
        }
        reverse_map[readable_path] = internal_path

    return readable_file_info, reverse_map



    
def insert_last_modified(file_info_dict, timestamp):
    last_modified_dict = {}
    for filepath, info in file_info_dict.items():
     
        uuid_cache = str(uuid.uuid4())
        last_modified_dict[filepath] = {
            "_name":info.get("_name"),
            "uuid_cache": uuid_cache,
            "last-modifier": info.get("last-modifier"),
            "timestamp": timestamp
        }
    return {"last-modified": last_modified_dict}


def create_cache_doc(db):
    cache_docs = db.collection("cache").stream()
    cache_doc = None
    for doc in cache_docs:
        cache_doc = doc  #if there is ONLY ONE DOCUMENT, which should be the case
        print(f"cache_doc= {cache_doc}")
    return cache_doc


