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
        
            if  (
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
    
"""
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
"""

def split_tree_with_name(realtime_tree, base_path=""):
    tree_structure = {} #creates tree firestore tree (keys are ids)
                        #folder have "_name" field, files have their names as string values of their ids.
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

        
            if isinstance(node, dict):
                names.append(node.get("_name", part))
            else:
                names.append(node)  
        else:
            names.append(part)  
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

def extract_paths_from_last_modified(document_data):
    paths = []

    if document_data:
        for key, value in document_data.items():
            # Each key is a path like 'main.tex', or 'NO_CHAPTERS_ALLOWED/...'
            if isinstance(value, dict) and '_name' in value:
                paths.append(key)
    else:
        print(f"No data found in document: {document_data}")

    print(f"Paths extracted by last-modified: {paths}")
    return paths

import uuid

def assign_uuids(paths):
    unique_parts = set()

    # Extract all unique path segments (folders and filenames)
    for path in paths:
        parts = path.split('/')
        unique_parts.update(parts)

    # Assign a UUID to each unique part
    uuid_map = {part: str(uuid.uuid4()) for part in unique_parts}

    print(f"uuid map: {uuid_map}")

    return uuid_map

def build_tree_with_uuids(paths, uuid_map):
    tree = {}

    for path in paths:
        parts = path.strip("/").split("/")
        current_level = tree

        for i, part in enumerate(parts):
            uuid_id = uuid_map[part]

            if i == len(parts) - 1:
                # Leaf: file
                if uuid_id in current_level and isinstance(current_level[uuid_id], dict):
                    print(f"⚠️ UUID conflict: tried to insert file '{part}' where folder already exists (UUID: {uuid_id})")
                current_level[uuid_id] = part
            else:
                # Folder
                if uuid_id not in current_level:
                    current_level[uuid_id] = {"_name": part}
                elif isinstance(current_level[uuid_id], str):
                    print(f"⚠️ UUID conflict: tried to use file '{part}' as folder (UUID: {uuid_id})")
                    continue  # or raise
                current_level = current_level[uuid_id]

    print("✅ Tree with UUIDs:", tree)
    return tree



def generate_uuid_path_map_from_tree(tree, current_path=""):
    uuid_path_map = {}

    for key, value in tree.items():
        if key == "_name":
            continue  # ignora _name come chiave esplicita, lo userai nel livello superiore

        if isinstance(value, dict):
            folder_name = value.get("_name", "")
            sub_path = f"{current_path}{folder_name}/" if folder_name else current_path
            sub_map = generate_uuid_path_map_from_tree(value, sub_path)
            uuid_path_map.update(sub_map)
        elif isinstance(value, str):
            # È un file, costruisci path completo
            full_path = f"{current_path}{value}"
            uuid_path_map[key] = full_path

    return uuid_path_map



def generate_uuid_path_map_from_cache(content_list):
    uuid_path_map = {}
    for item in content_list:
        uuid_id = item.get("uuid")
        path = item.get("path")
        if uuid_id and path:
            uuid_path_map[uuid_id] = path
    return uuid_path_map





def update_firestore_tree(tree: dict, added_items: list, deleted_paths: list):
    def find_subfolder_by_name(subtree: dict, name: str):
        for uuid_id, node in subtree.items():
            if isinstance(node, dict) and node.get("_name") == name:
                return uuid_id, node
        return None, None

    def remove_from_tree(subtree: dict, path_parts: list):
        """Recursively removes the file with a given path."""
        if len(path_parts) < 1:
            return

        folder_parts = path_parts[:-1]
        filename = path_parts[-1]
        current = subtree

        for part in folder_parts:
            folder_uuid, folder_node = find_subfolder_by_name(current, part)
            if not folder_node:
                return  # Path not found
            current = folder_node

        # Rimuove il file con nome corrispondente
        for uuid_id, value in list(current.items()):
            if isinstance(value, str) and value == filename:
                del current[uuid_id]
                break

    def insert_into_tree(subtree: dict, path_parts: list, uuid_id: str, filename: str):
        """Recursively inserts a file with uuid at the correct folder path."""
        current = subtree

        for folder_name in path_parts:
            folder_uuid, folder_node = find_subfolder_by_name(current, folder_name)
            if not folder_node:
                # Create the folder if it doesn't exist
                new_uuid = str(uuid.uuid4())
                current[new_uuid] = {"_name": folder_name}
                folder_uuid = new_uuid
                folder_node = current[folder_uuid]

            current = folder_node

        current[uuid_id] = filename  # insert file

    # === 1. Remove deleted/moved/renamed old paths ===
    for path in deleted_paths:
        parts = path.strip("/").split("/")
        remove_from_tree(tree, parts)

    # === 2. Add new/moved/renamed items ===
    for item in added_items:
        path = item.get("path")
        uuid_id = item.get("uuid")
        if not path or not uuid_id:
            continue
        parts = path.strip("/").split("/")
        filename = parts[-1]
        folder_parts = parts[:-1]
        insert_into_tree(tree, folder_parts, uuid_id, filename)

    return tree





    



