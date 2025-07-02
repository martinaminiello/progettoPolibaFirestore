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
    repository =  Repository(u)
    return repository





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



def assign_uuids(paths):
    unique_parts = set()

    # Extract all unique path segments (folders and filenames)
    for path in paths:
        parts = path.split('/')
        unique_parts.update(parts)

    # Assign a UUID to each unique part creating a dict
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
                    print(f"UUID conflict: tried to insert file '{part}' where folder already exists (UUID: {uuid_id})")
                current_level[uuid_id] = part
            else:
                # Folder
                if uuid_id not in current_level:
                    current_level[uuid_id] = {"_name": part}
                elif isinstance(current_level[uuid_id], str):
                    print(f"UUID conflict: tried to use file '{part}' as folder (UUID: {uuid_id})")
                    continue  # or raise
                current_level = current_level[uuid_id]

    print("Tree with UUIDs:", tree)
    return tree



def generate_uuid_path_map_from_tree(tree, current_path=""):
    uuid_path_map = {}

    for key, value in tree.items():
        if key == "_name":
            continue  # ignore _name 

        if isinstance(value, dict):
            folder_name = value.get("_name", "")
            sub_path = f"{current_path}{folder_name}/" if folder_name else current_path
            sub_map = generate_uuid_path_map_from_tree(value, sub_path)
            uuid_path_map.update(sub_map)
        elif isinstance(value, str):
            # file
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


def remove_empty_folders(subtree):
    """Recursively remove empty folders (dicts with only '_name')."""
    keys_to_delete = []
    for uuid_id, node in list(subtree.items()):
        if isinstance(node, dict):
            remove_empty_folders(node)
            #
            if list(node.keys()) == ["_name"]:
                keys_to_delete.append(uuid_id)
    for uuid_id in keys_to_delete:
        del subtree[uuid_id]


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

        # remove file
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

    # Remove deleted/moved/renamed old paths 
    for path in deleted_paths:
        parts = path.strip("/").split("/")
        remove_from_tree(tree, parts)

    # Add new/moved/renamed items 
    for item in added_items:
        path = item.get("path")
        uuid_id = item.get("uuid")
        if not path or not uuid_id:
            continue
        parts = path.strip("/").split("/")
        filename = parts[-1]
        folder_parts = parts[:-1]
        insert_into_tree(tree, folder_parts, uuid_id, filename)

    remove_empty_folders(tree)  

    return tree









