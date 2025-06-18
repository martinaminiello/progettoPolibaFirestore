import os
import uuid
import datetime
import time
from github import GithubException
from google.cloud.exceptions import GoogleCloudError
from google.cloud.firestore_v1 import DELETE_FIELD
import utils
from google.cloud.firestore_v1 import ArrayUnion
from google.cloud.firestore_v1 import ArrayRemove
from google.cloud import firestore
from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError, FailedPrecondition
import uuid
import time
from google.api_core.exceptions import FailedPrecondition
from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError, FailedPrecondition


def is_cache_stable(cache_doc, idle_seconds=2):
    """
    Returns True if no item in the queue has been updated in the last `idle_seconds`.
    """
    snapshot = cache_doc.reference.get()
    now = time.time()
    items = snapshot.to_dict().get("queue_item", [])

    for item in items:
        timestamp_obj = item.get("timestamp")
        if timestamp_obj is None:
            continue
        # Convert Firestore Timestamp to float seconds
        timestamp = timestamp_obj.timestamp()
        if now - timestamp < idle_seconds:
            return False
    return True



def create_tree_and_infos(event):
    old_tree_realtime = event.data.before.get("tree", {})
    old_tree_structure=utils.split_tree(old_tree_realtime)[0] #split tree to get the structure
    old_tree=utils.convert_tree_keys(old_tree_structure)
    print(f" Old tree: {old_tree}")
        
    new_tree_realtime = event.data.after.get("tree", {})
    new_tree_structure=utils.split_tree(new_tree_realtime)[0] #split tree to get the structure
    new_tree=utils.convert_tree_keys(new_tree_structure)
    print(f" New tree: {new_tree}")

    old_file_info = utils.split_tree(old_tree_realtime)[1]
    old_file_info_converted = utils.convert_tree_keys(old_file_info) #convert old file info keys to be compatible with firestore
    print(f" Old file info: {old_file_info_converted}")
        
    new_file_info = utils.split_tree(new_tree_realtime)[1]
    new_file_info_converted = utils.convert_tree_keys(new_file_info) #convert new file info keys to be compatible with firestore
    print(f" New file info: {new_file_info_converted}")

    return old_tree, new_tree, old_file_info_converted, new_file_info_converted


def create_tree_and_infos_names(event):
    old_tree_realtime = event.data.before.get("tree", {})
    print(f"[create_tree_and_infoS_names] old realtime tree: {old_tree_realtime}")
    old_tree_structure=utils.split_tree_with_name(old_tree_realtime)[0] #split tree to get the structure
   
    print(f" Old tree: {old_tree_structure}")
        
    new_tree_realtime = event.data.after.get("tree", {})
    new_tree_structure=utils.split_tree_with_name(new_tree_realtime)[0] #split tree to get the structure
    
    print(f" New tree: {new_tree_structure}")

    old_file_info = utils.split_tree_with_name(old_tree_realtime)[1]
    print(f" Old file info: {old_file_info}")
        
    new_file_info = utils.split_tree_with_name(new_tree_realtime)[1]
    print(f" New file info: {new_file_info}")

    return old_tree_structure, new_tree_structure, old_file_info, new_file_info


def set_nested_dict(tree, path, value):
    parts = path.split('/')
    d = tree
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]

    last_key = parts[-1]

    # Se il value è un dict, aggiorna (tipico delle cartelle)
    if isinstance(value, dict):
        if last_key not in d or not isinstance(d[last_key], dict):
            d[last_key] = {}
        d[last_key].update(value)
    else:
        # File: sovrascrivi direttamente
        d[last_key] = value


        # utility function: remove path from tree
def extract_all_paths(tree_map, current_path=""):
    paths = []

    for key, value in tree_map.items():
        new_path = f"{current_path}/{key}" if current_path else key
        if isinstance(value, dict):
            # Se è dict, ricorsivamente estrai solo i file
            paths.extend(extract_all_paths(value, new_path))
        else:
            # Se non è dict, è un file (o nodo foglia)
            paths.append(new_path)

    return paths


def remove_path_from_tree(tree, path):
    parts = path.split('/')
    d = tree
    for part in parts[:-1]:
        if part in d and isinstance(d[part], dict):
            d = d[part]
        else:
            return  # path not found
    d.pop(parts[-1], None)

def remove_empty_parents(tree, path):
    parts = path.split('/')
    for i in reversed(range(1, len(parts))):
        sub_path = parts[:i]
        d = tree
        valid = True
        for part in sub_path:
            if part in d and isinstance(d[part], dict):
                d = d[part]
            else:
                valid = False
                break
        if valid and not d:
            remove_path_from_tree(tree, '/'.join(sub_path))



def safe_delete_file(repo, path, max_retries=3):
    for attempt in range(max_retries):
        try:
            file = repo.get_contents(path)  
            repo.delete_file(file.path, f"Remove {path}", file.sha)
            print(f"Deleted {path}")
            return True
        except GithubException as e:
            if e.status == 404:
                print(f"File {path} not found on GitHub, skipping deletion.")
                return True
            elif e.status == 409:
                print(f"SHA mismatch for {path}. Retrying... ({attempt + 1})")
                time.sleep(0.5)
            else:
                raise
    print(f"Failed to delete {path} after {max_retries} attempts.")
    return False

def update_cache_in_progress(cache_doc, uuid_cache, content, path, timestamp): #from real-time is always in progress
    try:
        cache_doc.reference.update({
            "queue_item": ArrayUnion([{
                "uuid_cache": uuid_cache,
                "path": path,
                "content": content,
                "timestamp": timestamp,
                "push_status": "in-progress"
            }]),
           
        })
    except GoogleCloudError as e:
        print(f"Firestore update failed: {e}")

def failed_status(item, cache_doc):

        print(f"Failed to push item: {item}")
        # if it's a list update all items in the list
        if isinstance(item, list):
            items = item
        else:
            items = [item]
        for it in items:
            failed_item = dict(it)
            failed_item["push_status"] = "failed"
            cache_doc.reference.update({
                "queue_item": ArrayRemove([it])
                        })
            cache_doc.reference.update({
                "queue_item": ArrayUnion([failed_item])
                        })
         # TO DO: RETRY LOGIC

def clean_cache(path,cache_doc):
    cache_doc = cache_doc.reference.get()
    queue_items = cache_doc.to_dict().get("queue_item", [])
    to_remove = [item for item in queue_items if isinstance(item, dict) and item.get("path") == path]
    print(f"Removing all items from queue with path {path}: {to_remove}")
    if to_remove:
        cache_doc.reference.update({"queue_item": ArrayRemove(to_remove)})



class Repository:

    def __init__(self, user):
        self.user = user



    def get_current_repo(self, repo_name):
        username = self.user.username
        repo = self.user.github.get_repo(f"{username}/{repo_name}") # no os.path.join, github needs '/'
        print(f"Repo object retrieved from github: {repo}")
        return repo

    def get_repo_url(self, repo_name):
        url=self.user.user_url+repo_name
        return url



    def create_new_repo(self, repo_name):
        try:
            # create repository on git
            self.user.github.get_user().create_repo(name=repo_name)
        except GithubException as e:
            print(f"Status: {e.status}, Error: ", e)
            if e.status == 422:
                print(f"Repository already exists! No need to create another one")
                return


    def extract_file_paths(self, tree_map, current_path=""):
        paths = []

        if not isinstance(tree_map, dict):
            return paths

        for key, value in tree_map.items():
            new_path = f"{current_path}/{key}" if current_path else key
            if isinstance(value, dict):
                # Se è un file con content + last-modifier, consideralo foglia
                if "content" in value and "last-modifier" in value:
                    paths.append(new_path)
                else:
                    # Altrimenti è una cartella, continua
                    paths.extend(self.extract_file_paths(value, new_path))
            elif isinstance(value, str):
                if not key.startswith("id_"):  # ignora metadati come id_file/id_folder
                    paths.append(new_path)
        return paths
    
    def extract_file_paths_with_names(self, tree_map, current_path=""):
        paths = []

        if not isinstance(tree_map, dict):
            return paths

        for key, value in tree_map.items():
            if key == "_name":
                # Ignoro il nome della cartella stessa, serve solo per leggibilità
                continue

            if isinstance(value, str):
                # È un file: value è il nome leggibile del file
                file_path = f"{current_path}/{value}" if current_path else value
                paths.append(file_path)

            elif isinstance(value, dict):
                # È una cartella: ricorsione
                folder_name = value.get("_name", key)
                new_path = f"{current_path}/{folder_name}" if current_path else folder_name
                sub_paths = self.extract_file_paths_with_names(value, new_path)
                paths.extend(sub_paths)

            else:
                # Caso anomalo, logga per debug
                print(f"[WARN] Nodo non dict e non string: {key} -> {value}")

        return paths



    



    def create_tree(self, file_paths, repo_name,last_modified_info, cache_doc):
        print(f"Repo name: {repo_name}")
        repo = self.get_current_repo(repo_name)

        # Ensure last_modified_info is always a dict
        if last_modified_info is None:
            last_modified_info = {}
        print(f"Last modified info: {last_modified_info}")
        

        for path in file_paths:
            print(f"Processing path: {path}")
            file_info = last_modified_info.get(path, {})
            queue_items = cache_doc.to_dict().get("queue_item", [])
            author = file_info.get("last-modifier")
            uuid_cache = file_info.get("uuid_cache")
            content = None
            for item in queue_items:
                print(f"[DEBUG] Matching queue path {item.get('path')} == {path}? uuid_cache {item.get('uuid_cache')} == {uuid_cache}")

                if item.get("path") == path and item.get("uuid_cache") == uuid_cache:
                    content = item.get("content")
                    break
            print(f"Creating file at {path} with content: {repr(content)} e author: {author}")
            try:
                repo.create_file(path, f"Add file {path}, version: {uuid_cache}", content)
                print(f"File created at {path} with content: {repr(content)}")

                clean_cache(path, cache_doc)
                
             
            except GithubException as e:
                if e.status == 422:
                    print(f"File already exists: {path}")
                else:
                    print(f"Error creating new file: {path}: {e}")

    def build_nested_update(self,path, value):
        parts = path.split('/')
        update_dict = current = {}
        for part in parts[:-1]:
            current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        return update_dict



    def detect_and_apply_renames(self, old_tree, new_tree, doc_ref, db):
        def recurse(old_node, new_node, current_path):
            for key in new_node:
                if key.startswith(('f_', 'd_')) and key in old_node:
                    old_sub = old_node[key]
                    new_sub = new_node[key]

                    if isinstance(old_sub, dict) and isinstance(new_sub, dict):
                        full_path = f"{current_path}/{key}" if current_path else key  # <- Spostato fuori

                        old_name = old_sub.get("_name")
                        new_name = new_sub.get("_name")

                        if old_name and new_name and old_name != new_name:
                            print(f"[RENAME DETECTED] {full_path}: '{old_name}' ➜ '{new_name}'")
                            doc_ref.update({self.firestore_path(f"{full_path}/_name"): new_name})

                        recurse(old_sub, new_sub, full_path)

        recurse(old_tree, new_tree, "")


    def firestore_path(self, path):
        return f"tree.{path.replace('/', '.')}"




    def get_renamed_paths(self, old_tree, new_tree, parent_old="", parent_new=""):
        renamed = {}

        old_keys = set(old_tree.keys())
        new_keys = set(new_tree.keys())

        for key in old_keys & new_keys:
            old_val = old_tree[key]
            new_val = new_tree[key]

            if key.startswith("d_") and isinstance(old_val, dict) and isinstance(new_val, dict):
                old_name = old_val.get("_name", "")
                new_name = new_val.get("_name", "")

                old_parent = f"{parent_old}/{old_name}" if parent_old else old_name
                new_parent = f"{parent_new}/{new_name}" if parent_new else new_name

                # Ricorsione per le sottocartelle e file dentro questa cartella
                renamed.update(self.get_renamed_paths(old_val, new_val, old_parent, new_parent))

            elif key.startswith("f_"):
                # Estrai il nome del file dai dizionari
                old_file_name = old_val.get("_name") if isinstance(old_val, dict) else old_val
                new_file_name = new_val.get("_name") if isinstance(new_val, dict) else new_val

                old_path = f"{parent_old}/{old_file_name}" if parent_old else old_file_name
                new_path = f"{parent_new}/{new_file_name}" if parent_new else new_file_name

                if old_path != new_path:
                    renamed[old_path] = new_path

        return renamed

    def get_named_path(self,tree, path):
      
        parts = path.split("/")
        named_parts = []
        current = tree

        for part in parts:
            if part not in current:
                raise KeyError(f"'{part}' non trovato nel tree")
            node = current[part]

            # Aggiunge il valore di "_name" se esiste, altrimenti la chiave grezza
            named_parts.append(node.get("_name", part))

            # Scende nel livello successivo se è un dizionario
            current = node if isinstance(node, dict) else {}

        return "/".join(named_parts)





    def update_firestore(self, event, repo_name, doc_ref, cache_doc, timestamp):
        MAX_RETRIES = 10

        old_tree_realtime = event.data.before.get("tree", {})
        print(f"[update_firestore] old realtime tree: {old_tree_realtime}")
        new_tree_realtime = event.data.after.get("tree", {})
        print(f"[update_firestore] new realtime tree: {new_tree_realtime}")
        doc = doc_ref.get()
        data = doc.to_dict()
        old_tree_firestore = data.get("tree")
        print(f"[update_firestore] old firestore tree: {old_tree_firestore}")
        new_tree_firestore, last_modified_info = utils.split_tree_with_name(new_tree_realtime)
        print(f"[update_firestore] new firestore tree: {new_tree_firestore}")
        print(f"[update_firestore] new last_modified_info : {last_modified_info}")


        old_tree, new_tree, old_info, new_info = create_tree_and_infos_names(event)
        print(f"Initial tree  state for {repo_name} - old_tree: {old_tree}, new_tree: {new_tree}, doc_ref: {doc_ref}, old_info: {old_info}, new_info: {new_info}")

        db = firestore.Client()
        transaction = db.transaction()

       

        #renaming
        self.detect_and_apply_renames(old_tree, new_tree, doc_ref, db)   
        old_to_new_paths = self.get_renamed_paths(old_tree_realtime, new_tree_realtime)
        

        @firestore.transactional
        def transaction_operation(transaction):
            doc = doc_ref.get(transaction=transaction)
            data = doc.to_dict() or {}
            if "tree" not in data or not isinstance(data["tree"], dict):
             data["tree"] = {}
            
            if "last-modified" not in data or not isinstance(data["last-modified"], dict):
                data["last-modified"] = {}

            for old_path, new_path in old_to_new_paths.items():
                if old_path in data["last-modified"]:
                    data["last-modified"][new_path] = data["last-modified"].pop(old_path)
                    print(f"Updated last-modified from {old_path} to {new_path}")



            old_paths = set(self.extract_file_paths(old_tree))
            new_paths = set(self.extract_file_paths(new_tree))

            print(f"Transaction update attempt: {repo_name}")
            print("Old paths:", old_paths)
            print("New paths:", new_paths)

            if "tree" not in data or not isinstance(data["tree"], dict):
                data["tree"] = {}
            if "last-modified" not in data or not isinstance(data["last-modified"], dict):
                data["last-modified"] = {}

            
           
            for path in old_paths & new_paths:
                if path.endswith("/_name"):
                     continue
                old_path_with_names=self.get_named_path(old_tree_realtime, path)
                new_path_with_names=self.get_named_path(new_tree_realtime, path)
                print("Renamed folders?", old_path_with_names!=new_path_with_names)
                print(f"new path: ",old_path_with_names)
                print(f"old path: ",new_path_with_names)
                 


          
            modified = set()

            for path in old_paths & new_paths:
                if path.endswith("/_name"):
                    continue

                old_content = old_info.get(path, {}).get("content")
                new_content = new_info.get(path, {}).get("content")
                old_name = old_info.get(path, {}).get("_name")
                new_name = new_info.get(path, {}).get("_name")

                old_named_path = self.get_named_path(old_tree_realtime, path)
                new_named_path = self.get_named_path(new_tree_realtime, path)

                if (
                    old_content != new_content
                    or old_name != new_name
                    or old_named_path != new_named_path
                ):
                    modified.add(path)

            added = (new_paths - old_paths) - modified
            deleted = (old_paths - new_paths) - modified

            print("Modified paths:", modified)
            print("Added paths:", added)
            print("Deleted paths:", deleted)

            for path in modified:
                print(f"Modifying file at {path} (content or name changed)")
                file_info = new_info.get(path, {})
                content = file_info.get("content", "")
                last_modifier = file_info.get("last-modifier", "")
                uuid_cache = str(uuid.uuid4())
                
                print(f"Calling get_named_path with path={path} and type={type(path)}")
                names_path= self.get_named_path(new_tree_realtime,path)

                print(f"names path {names_path}")
                print(f"path {path}")

                # Aggiorna anche il nome nel tree!
                set_nested_dict(data["tree"], path, file_info.get("_name", ""))

                #serve altro

             
                print(f"path in modified : {names_path}")
                data["last-modified"][names_path] = {
                    "last-modifier": last_modifier,
                    "uuid_cache": uuid_cache,
                    "timestamp": timestamp
                }
                print(f"Updating cahce in progress...path: {names_path} uuidcache: {uuid_cache},content: {content}")
                update_cache_in_progress(cache_doc, uuid_cache, content, names_path, timestamp)        

            for path in deleted:
                print("To delete:", path)
                try:
                    remove_path_from_tree(data["tree"], path)
                    remove_empty_parents(data["tree"], path)
                    data["last-modified"].pop(path, None)
                    print(f"Deleted: {path}")
                except Exception as e:
                    print(f"Error deleting path {path} in transaction: {e}")

            for path in added:
                print("To add:", path)
                file_info = new_info.get(path, {})
                content = file_info.get("content", "")
                last_modifier = file_info.get("last-modifier", "")

                if not content and not last_modifier:
                    file_info = utils.insert_last_modified(new_info, timestamp).get("last-modified", {}).get(path, {})
                    content = file_info.get("content", "")
                    last_modifier = file_info.get("last-modifier", "")

                uuid_cache = str(uuid.uuid4())

                print(f"Adding file at {path} with content: {repr(content)} and last modifier: {last_modifier}")
                set_nested_dict(data["tree"], path, "")
                data["last-modified"][path] = {
                    "last-modifier": last_modifier,
                    "uuid_cache": uuid_cache,
                    "timestamp": timestamp
                }

                update_cache_in_progress(cache_doc, uuid_cache, content, path, timestamp)

            print(f"Tree after operations in transaction: {data['tree']}")
            transaction.update(doc_ref, {
                "tree": data["tree"],
                "last-modified": data["last-modified"],
                "last-edit": timestamp
            })

        for attempt in range(MAX_RETRIES):
            try:
                transaction_operation(transaction)
                print(f"Firestore document updated successfully for {repo_name}")
                break
            except FailedPrecondition as e:
                print(f"[RACE CONDITION] Transaction failed (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    print("[ERROR] Max retries reached. Transaction aborted.")
                    raise
            except GoogleAPICallError as e:
                print(f"[ERROR] Firestore API call failed during transaction: {e}")
                raise

    def extract_paths(self,tree, parent_path=""):
        paths = []

        for key, value in tree.items():
            if key.startswith("d_") and isinstance(value, dict):
                # Cartella: prendo il nome della cartella da _name
                folder_name = value.get("_name", "")
                # Nuovo path di partenza
                new_parent_path = f"{parent_path}/{folder_name}" if parent_path else folder_name
                # Ricorsione sulla sottocartella
                paths.extend(self.extract_paths(value, new_parent_path))

            elif key.startswith("f_"):
                # File: valore è il nome del file
                file_name = value
                # Creo il path completo
                file_path = f"{parent_path}/{file_name}" if parent_path else file_name
                paths.append(file_path)

        return paths
    
    def extract_file_id_to_path(self,tree, parent_path=""):
        id_to_path = {}

        for key, value in tree.items():
            if key.startswith("d_") and isinstance(value, dict):
                folder_name = value.get("_name", "")
                new_parent_path = f"{parent_path}/{folder_name}" if parent_path else folder_name
                id_to_path.update(self.extract_file_id_to_path(value, new_parent_path))

            elif key.startswith("f_"):
                file_id = key
                file_name = value
                file_path = f"{parent_path}/{file_name}" if parent_path else file_name
                id_to_path[file_id] = file_path

        return id_to_path

    


    def update_tree(self, old_tree, new_tree, repo_name, doc_ref, old_info, new_info, cache_doc):
        repo = self.get_current_repo(repo_name)
        print(f"[update_tree] {repo_name} | old_tree: {old_tree}, new_tree: {new_tree}, newinfo {new_info}")

        # Ensure Firestore queue is stable before proceeding
        MAX_WAIT = 8
        WAIT_INTERVAL = 1
        print("[sync] Waiting for Firestore to stabilize...")
        for _ in range(MAX_WAIT):
            if is_cache_stable(cache_doc):
                print("[sync] Firestore stable. Proceeding.")
                break
            time.sleep(WAIT_INTERVAL)
        else:
            print("[sync] Timeout waiting for Firestore stabilization. Proceeding anyway.")

        # Extract file paths from trees
        old_paths = set(self.extract_paths(old_tree))
        new_paths = set(self.extract_paths(new_tree))
        print(f"Old paths {old_paths}")
        print(f"New paths {new_paths}")

        # Extract ID-to-path mappings to detect renames
        old_id_to_path = self.extract_file_id_to_path(old_tree)
        new_id_to_path = self.extract_file_id_to_path(new_tree)

        renamed_files = []
        for file_id in old_id_to_path:
            if file_id in new_id_to_path:
                old_path = old_id_to_path[file_id]
                new_path = new_id_to_path[file_id]
                if old_path != new_path:
                    renamed_files.append((old_path, new_path))

        # ------------------------
        # Handle Renamed Files
        # ------------------------
        snapshot = cache_doc.reference.get()
        update_time = snapshot.update_time
        queue_items = snapshot.to_dict().get("queue_item", [])
        print(f"cache queue: {queue_items}")
        snapshot = doc_ref.get()
        new_info_dict = snapshot.to_dict() or {}
        new_info=new_info_dict["last-modified"]
        print(f"New info: {new_info}")
        
        for old_path, new_path in renamed_files:
            print(f"[rename] {old_path} -> {new_path}")
            try:
                file_info = new_info.get(new_path, {})

                print(f"File info last-modified: {file_info}")
                
                uuid_cache = file_info.get("uuid_cache", "")
                if not uuid_cache:
                    print(f"[warn] Missing uuid_cache for {new_path}, skipping")
                    continue

                content = None
                snapshot = cache_doc.reference.get()
                update_time = snapshot.update_time
                queue_items = snapshot.to_dict().get("queue_item", [])

                for item in queue_items:
                    if item.get("uuid_cache") == uuid_cache:
                        content = item.get("content")
                        break

                if content is None:
                    print(f"[warn] Content not found for {new_path} with uuid {uuid_cache}, skipping")
                    continue

                # Delete the old file and create the new one with the content
                file = repo.get_contents(old_path)
                repo.delete_file(old_path, f"Rename {old_path} to {new_path}", file.sha)
                repo.create_file(new_path, f"Rename {old_path} to {new_path}", content)

                print(f"[rename] Successfully renamed {old_path} -> {new_path}")
                clean_cache(old_path, cache_doc)
                clean_cache(new_path, cache_doc)

            except GithubException as e:
                print(f"[error] Rename failed from {old_path} to {new_path}: {e}")

        # Remove renamed paths from diff sets
        old_paths -= {old for old, _ in renamed_files}
        new_paths -= {new for _, new in renamed_files}

        # ------------------------
        # Handle Deleted Files
        # ------------------------
        for path in old_paths - new_paths:
            print(f"[delete] {path}")
            try:
                safe_delete_file(repo, path)
            except GoogleCloudError as e:
                print(f"[error] Deleting {path} failed: {e}")
            except GithubException as e:
                if e.status == 409:
                    try:
                        live_contents = repo.get_contents(path)
                        repo.delete_file(path, f"Delete {path}", live_contents.sha)
                    except GithubException as e2:
                        print(f"[delete] Still failed to delete {path}: {e2}")
                else:
                    raise
            clean_cache(path, cache_doc)

        # ------------------------
        # Handle Added Files
        # ------------------------
        for path in new_paths - old_paths:
            print(f"[add] {path}")
            file_info = new_info.get(path, {})
            uuid_cache = file_info.get("uuid_cache", "")
            content = None

            snapshot = cache_doc.reference.get()
            update_time = snapshot.update_time
            queue_items = snapshot.to_dict().get("queue_item", [])

            for item in queue_items:
                if item.get("uuid_cache") == uuid_cache:
                    content = item.get("content")
                    break

            if content is None:
                print(f"[warn] Content not found for {path} with uuid {uuid_cache}, skipping")
                continue

            try:
                # Remove queue item
                to_remove = [item for item in queue_items if item.get("path") == path]
                if to_remove:
                    cache_doc.reference.update(
                        {"queue_item": ArrayRemove(to_remove)},
                        firestore.Client.write_option(last_update_time=update_time)
                    )

                # Create the file on GitHub
                repo.create_file(path, f"Add {path}, version {uuid_cache}", content)
                print(f"[add] Successfully created {path}")
            except FailedPrecondition:
                print(f"[firestore] Precondition failed when adding {path}")
            except GithubException as e:
                print(f"[github] Failed to create {path}: {e}")
                failed_status(item, cache_doc)
                if e.status == 409:
                    time.sleep(1)
                    repo.create_file(path, f"Add {path}, version {uuid_cache}", content)
                    print(f"[add] Successfully created {path}")
            except GithubException as e2:
                print(f"[github] Still failed to recreate {path}: {e2}")

            clean_cache(path, cache_doc)

        # ------------------------
        # Handle Modified Files
        # ------------------------
        for path in old_paths & new_paths:
            old_uuid = old_info.get(path, {}).get("uuid_cache")
            new_uuid = new_info.get(path, {}).get("uuid_cache")
            old_content = old_info.get(path, {}).get("content")
            new_content = new_info.get(path, {}).get("content")
            print(f"old uuid {old_uuid}, new uuid {new_uuid}")
            print(f"old content {old_content}, new content {new_content}")


            if old_uuid == new_uuid:
                continue  # No change
            if old_content== new_content:
                continue

            print(f"[modify] Updating {path}")
            for attempt in range(10):
                snapshot = cache_doc.reference.get()
                update_time = snapshot.update_time
                queue_items = snapshot.to_dict().get("queue_item", [])
                item = next((i for i in queue_items if i.get("uuid_cache") == new_uuid), None)
                if not item:
                    time.sleep(0.5)
                    continue  # Retry

                try:
                    file = repo.get_contents(path)
                    repo.update_file(path, f"Update {path}, version {new_uuid}", item["content"], file.sha)
                    print(f"[modify] Updated {path} to version {new_uuid}")

                    # Clean queue
                    to_remove = [item]
                    if to_remove:
                        cache_doc.reference.update(
                            {"queue_item": ArrayRemove(to_remove)},
                            firestore.Client.write_option(last_update_time=update_time)
                        )
                    break
                except GithubException as e:
                    print(f"[github] Failed to update {path}: {e}")
                    if e.status == 409:
                        time.sleep(1)
                        continue
                    failed_status(item, cache_doc)
                    break

            clean_cache(path, cache_doc)








    def delete_project(self, repo_name):
        repo = self.get_current_repo(repo_name)
        try:
            repo.delete()
            print(f"Repository {repo_name} deleted successfully")
        except GithubException as e:
            print(f"Error deleting {repo}: {e}")



















