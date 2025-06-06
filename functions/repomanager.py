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


def set_nested_dict(tree, path, value):
    parts = path.split('/')
    d = tree
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value

        # utility function: remove path from tree
def remove_path_from_tree(tree, path):
    parts = path.split('/')
    d = tree
    for part in parts[:-1]:
        if part in d and isinstance(d[part], dict):
           d = d[part]
        else:
            return  # path not found
    d.pop(parts[-1], None)

def remove_from_cache(cache_doc, uuid_cache=None, path=None):
    queue_items = cache_doc.to_dict().get("queue_item", [])
    # Rimuovi tutti gli item con push_status 'done' (per path se specificato, altrimenti tutti)
    print(f"items in queue_item before removal: {queue_items}")
    to_remove = [item for item in queue_items if isinstance(item, dict) and item.get("push_status") == "in-progress"]
    if to_remove:
        print("Sto rimuovendo da queue_item:", to_remove)
        cache_doc.reference.update({
            "queue_item": ArrayRemove(to_remove)
        })

def update_cache_in_progress(cache_doc, uuid_cache, content): #from real-time is always in progress
    try:
        cache_doc.reference.update({
            "queue_item": ArrayUnion([{
                "uuid_cache": uuid_cache,
                "content": content,
                "push_status": "in-progress"
            }]),
           
        })
    except GoogleCloudError as e:
        print(f"Firestore update failed: {e}")

def failed_status(found_in_queue, item, cache_doc):

    if found_in_queue and item:
        failed_item = dict(item)
        failed_item["push_status"] = "failed"
        cache_doc.reference.update({
            "queue_item": ArrayRemove([item])
                        })
        cache_doc.reference.update({
            "queue_item": ArrayUnion([failed_item])
                        })
         # TO DO: RETRY LOGIC


def put_in_queue(uuid_cache,path, content, cache_doc):
     # remove duplicates from queue and queue_item

    queue_items = cache_doc.to_dict().get("queue_item", [])
    push_queue = cache_doc.to_dict().get("queue", [])
    queue_items = [item for item in queue_items if item.get("uuid_cache") != uuid_cache]
    push_queue = [item for item in push_queue if item.get("uuid_cache") != uuid_cache]

     # update
    push_queue.append({
        "uuid_cache": uuid_cache,
        "path": path
                        })
    queue_items.append({
            "uuid_cache": uuid_cache,
            "path": path,
            "content": content,
            "push_status": "in-queue",
                        })

    # save in document
    cache_doc.reference.update({
            "queue": push_queue,
            "queue_item": queue_items
                        })



def process_queue(repo, cache_doc):
    MAX_ATTEMPTS = 5

    # Refresh Firestore snapshot at the start
    cache_doc = cache_doc.reference.get()
    data = cache_doc.to_dict()
    push_queue = data.get("queue", [])
    queue_items = data.get("queue_item", [])
    updated_uuids = []

    # Early exit if queue is empty or no in-queue items
    if not push_queue or not any(item.get("push_status") == "in-queue" for item in queue_items):
        print("Queue is empty or no in-queue items. Exiting process_queue.")
        return

    for item in list(push_queue):
        uuid_cache = item.get("uuid_cache")
        path = item.get("path")

        # Trova l'entry corrispondente in queue_items
        queue_entry = next((i for i in queue_items if i.get("uuid_cache") == uuid_cache), None)
        if not queue_entry:
            continue

        # Retry logic: check attempts
        attempts = queue_entry.get("attempts", 0)
        if queue_entry.get("push_status") == "failed" or attempts >= MAX_ATTEMPTS:
            # Mark as failed if not already
            if queue_entry.get("push_status") != "failed":
                failed_item = dict(queue_entry)
                failed_item["push_status"] = "failed"
                cache_doc.reference.update({
                    "queue_item": ArrayRemove([queue_entry])
                })
                cache_doc.reference.update({
                    "queue_item": ArrayUnion([failed_item])
                })
            # Remove from push_queue
            cache_doc.reference.update({
                "queue": ArrayRemove([item])
            })
            continue

        # Aggiorna lo status a in-progress su Firestore se era in-queue
        if queue_entry.get("push_status") == "in-queue":
            old_entry = dict(queue_entry)
            queue_entry = dict(queue_entry)
            queue_entry["push_status"] = "in-progress"
            queue_entry["attempts"] = attempts + 1
            cache_doc.reference.update({
                "queue_item": ArrayRemove([old_entry])
            })
            cache_doc.reference.update({
                "queue_item": ArrayUnion([queue_entry])
            })
            cache_doc.reference.update({
                "queue": ArrayRemove([item])
            })

        content = queue_entry.get("content")

        try:
            file = repo.get_contents(path)
            repo.update_file(file.path, f"Queued update {path}, version {uuid_cache}", content or "", file.sha)
            print(f"✅ Push dalla coda avvenuto con successo: {path} for content {content}")
            updated_uuids.append(uuid_cache)
            # Remove from queue_item after success
            cache_doc.reference.update({
                "queue_item": ArrayRemove([queue_entry])
            })
        except GithubException as e:
            if e.status == 409:
                print(f"⚠️ Conflitto SHA per {path}, lascio in coda.")
                # Incrementa attempts
                if attempts + 1 >= MAX_ATTEMPTS:
                    failed_item = dict(queue_entry)
                    failed_item["push_status"] = "failed"
                    cache_doc.reference.update({
                        "queue_item": ArrayRemove([queue_entry])
                    })
                    cache_doc.reference.update({
                        "queue_item": ArrayUnion([failed_item])
                    })
                else:
                    # Ritardo solo se ci sono altri item con stesso path ma uuid diverso
                    other_same_path = any(
                        (isinstance(q, dict) and q.get("path") == path and q.get("uuid_cache") != uuid_cache)
                        for q in queue_items
                    )
                    if other_same_path:
                        delay = min(2 ** (attempts + 1), 5)  # max 30 secondi
                        print(f"⏳ Attendo {delay} secondi prima di riprovare {path} (tentativo {attempts + 1}) perché ci sono altri commit concorrenti su questo file.")
                        time.sleep(delay)
                    # Rimetti in coda con attempts incrementato
                    new_entry = dict(queue_entry)
                    new_entry["push_status"] = "in-queue"
                    new_entry["attempts"] = attempts + 1
                    cache_doc.reference.update({
                        "queue_item": ArrayRemove([queue_entry])
                    })
                    cache_doc.reference.update({
                        "queue_item": ArrayUnion([new_entry])
                    })
                    cache_doc.reference.update({
                        "queue": ArrayUnion([item])
                    })
            else:
                print(f"❌ Errore generico per {path}: {e}")
                # Mark as failed if max attempts reached
                if attempts + 1 >= MAX_ATTEMPTS:
                    failed_item = dict(queue_entry)
                    failed_item["push_status"] = "failed"
                    cache_doc.reference.update({
                        "queue_item": ArrayRemove([queue_entry])
                    })
                    cache_doc.reference.update({
                        "queue_item": ArrayUnion([failed_item])
                    })
                else:
                    failed_status(True, queue_entry, cache_doc)

    # Refresh Firestore snapshot at the end
    cache_doc = cache_doc.reference.get()
    data = cache_doc.to_dict()
    push_queue = data.get("queue", [])
    queue_items = data.get("queue_item", [])
    # Only recurse if there are still in-queue items
    if push_queue and any(item.get("push_status") == "in-queue" for item in queue_items):
        process_queue(repo, cache_doc)
    else:
        print("Queue processing complete. No more in-queue items.")

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
            print("Tree map is not a dictionary.")
            return paths

        for key, value in tree_map.items():
            if isinstance(value, dict) and "content" in value and "last-modifier" in value:
                new_path = f"{current_path}/{key}" if current_path else key
                paths.append(new_path)
            else:
                new_path = f"{current_path}/{key}" if current_path else key
                if isinstance(value, dict):
                    paths.extend(self.extract_file_paths(value, new_path))
                elif isinstance(value, str):
                    new_path = f"{current_path}/{key}" if current_path else key
                    paths.append(new_path)
        return paths

    


    def create_tree(self, file_paths, repo_name, last_modified_info):
        print(f"Repo name: {repo_name}")
        repo = self.get_current_repo(repo_name)

        # Ensure last_modified_info is always a dict
        if last_modified_info is None:
            last_modified_info = {}
        print(f"Last modified info: {last_modified_info}")
        

        for path in file_paths:
            print(f"Processing path: {path}")
            file_info = last_modified_info.get(path, {})
            content = file_info.get("content", "")
            author = file_info.get("last-modifier")
            uuid_cache = file_info.get("uuid_cache")
            print(f"Creating file at {path} with content: {repr(content)} e author: {author}")
            try:
                repo.create_file(path, f"Add file {path}, version: {uuid_cache}", content)
                print(f"File created at {path} with content: {repr(content)}")
             
            except GithubException as e:
                if e.status == 422:
                    print(f"File already exists: {path}")
                else:
                    print(f"Error creating new file: {path}: {e}")


    def update_firestore(self, old_tree, new_tree, repo_name, doc_ref, old_info, new_info, cache_doc):
            repo = self.get_current_repo(repo_name)
            print(f" update_tree_fireatore: {repo_name} - old_tree: {old_tree}, new_tree: {new_tree}, doc_ref: {doc_ref}, old_info: {old_info}, new_info: {new_info}")
            old_paths = set(self.extract_file_paths(old_tree))
            new_paths = set(self.extract_file_paths(new_tree))

            print(f"File info dict: {new_info}")
            new_modified_dict = utils.insert_last_modified(new_info)["last-modified"] #updates dictinary with new paths
    

            doc = doc_ref.get()
            data = doc.to_dict() or {}
            #if tree or last-modified are not present, initialize them
            if "tree" not in data or not isinstance(data["tree"], dict):
                data["tree"] = {}
            if "last-modified" not in data or not isinstance(data["last-modified"], dict):
                data["last-modified"] = {}



            # DELETED file: files that are no longer in new paths
            deleted = old_paths - new_paths
            print("old_paths:", old_paths)
            print("new_paths:", new_paths)
            for path in deleted:
                print("To delete: ", path)
                try:
                    # REMOVE path from tree and last-modified
                    remove_path_from_tree(data["tree"], path)
                    timestamp = datetime.datetime.now(datetime.timezone.utc)
                    try:
                     doc_ref.update({
                        "last-edit": timestamp
                    })
                    except GoogleCloudError as e:
                        print(f"Firestore update failed for last-edited: {e}")
                except GoogleCloudError as e:
                    print(f"Unexpected error in Firestore deleting {path}: {e}")
                
                #removes paths in last-modified
                if path in data["last-modified"]:
                    del data["last-modified"][path]
                print(f"Deleted: {path}")

            # ADDED files: files that aren't in old paths
            added = new_paths - old_paths
            print("old_paths:", old_paths)
            print("new_paths:", new_paths)
            print(f"new_info chiavi: {list(new_info.keys())}")
          
            for path in added:
                print("To add: ", path)
                file_info = new_info.get(path, {})
                content = file_info.get("content", "")
                last_modifier = file_info.get("last-modifier", "")
                if not content and not last_modifier:
                    file_info = new_modified_dict.get(path, {})
                    content = file_info.get("content", "")
                    last_modifier = file_info.get("last-modifier", "")
                uuid_cache = str(uuid.uuid4())
                timestamp = datetime.datetime.now(datetime.timezone.utc)
                print(f"Adding file at {path} with content: {repr(content)} and last modifier: {last_modifier}")
                # Update the tree structure (not on firestore yet)
                set_nested_dict(data["tree"], path, "")
                # Update the last-modified info (not on firestore yet)
                data["last-modified"][path] = {
                    "last-modifier": last_modifier,
                    "uuid_cache": uuid_cache,
                    "timestamp": timestamp
                }
                
                update_cache_in_progress(cache_doc, uuid_cache, content)
                

                try:
                    doc_ref.update({
                        "last-edit": data["last-modified"][path]["timestamp"]
                    })
                except GoogleCloudError as e:
                    print(f"Firestore update failed for last-edited: {e}")
                
            
            try: 
                print(f"Updating Firestore document with {data['tree']} and {data['last-modified']}")
                # update the Firestore document with the new tree and last-modified info
                doc_ref.update({
                    "tree": data["tree"],
                    "last-modified": data["last-modified"]
                })
                print(f"Firestore document updated successfully for {repo_name}")
                

            except GoogleCloudError as e:
                print(f"Firestore update failed: {e}")

            #MODIFIED files: files that are in both old and new paths
            modified = old_paths & new_paths
            for path in modified:
                if new_info.get(path, {}).get("content") != old_info.get(path, {}).get("content"):
                    print(f"Modifying file at {path}")
                    file_info = new_info.get(path, {})
                    content = file_info.get("content", "")
                    last_modifier = file_info.get("last-modifier", "")
                    uuid_cache = str(uuid.uuid4())
                    timestamp = datetime.datetime.now(datetime.timezone.utc)
                    
                    print(f"Modified: {path}")
                    # Update the last-modified info
                    data["last-modified"][path] = {
                            "last-modifier": last_modifier,
                            "uuid_cache": uuid_cache,
                            "timestamp": timestamp
                        }
                    
                    update_cache_in_progress(cache_doc, uuid_cache, content)
                        
                    try:
                            doc_ref.update({
                                "last-edit": data["last-modified"][path]["timestamp"]
                            })
                    except GoogleCloudError as e:
                            print(f"Firestore update failed: {e}")
                        
    
            # update the Firestore document with the new tree and last-modified info
            try:
                doc_ref.update({
                    "tree": data["tree"],
                    "last-modified": data["last-modified"]
                })
            except GoogleCloudError as e:
                print(f"Firestore update failed: {e}")




    def update_tree(self, old_tree, new_tree, repo_name, doc_ref, old_info, new_info, cache_doc):
        repo = self.get_current_repo(repo_name)
        print(f" update_tree: {repo_name} - old_tree: {old_tree}, new_tree: {new_tree}, doc_ref: {doc_ref}, old_info: {old_info}, new_info: {new_info}")
        old_paths = set(self.extract_file_paths(old_tree))
        new_paths = set(self.extract_file_paths(new_tree))

        print(f"File info dict: {new_info}")
        

        doc = doc_ref.get()
        data = doc.to_dict() or {}
        #if tree or last-modified are not present, initialize them
        if "tree" not in data or not isinstance(data["tree"], dict):
            data["tree"] = {}
        if "last-modified" not in data or not isinstance(data["last-modified"], dict):
            data["last-modified"] = {}

      

        # DELETED file: files that are no longer in new paths
        deleted = old_paths - new_paths
        print("old_paths:", old_paths)
        print("new_paths:", new_paths)
        for path in deleted:
            print("To delete: ", path)
            try:
                file = repo.get_contents(path)
                repo.delete_file(file.path, f"Remove {path}", file.sha)
            except GithubException as e:
                print(f"Error deleting {path}: {e}")


        # ADDED files: files that aren't in old paths
        added = new_paths - old_paths
        print("old_paths:", old_paths)
        print("new_paths:", new_paths)
        print(f"new_info chiavi: {list(new_info.keys())}")
        added_success = set()
        for path in added:
            print("To add: ", path)
            file_info = new_info.get(path, {})
            last_modifier = file_info.get("last-modifier", "")
            uuid_cache = file_info.get("uuid_cache", "")
            queue_items = cache_doc.to_dict().get("queue_item", [])
            content = None
            for item in queue_items:
                if isinstance(item, dict) and item.get("uuid_cache") == uuid_cache:
                    content = item.get("content")
                    break
        
            print(f"Adding file at {path} with content: {repr(content)} and last modifier: {last_modifier}")


            
            try:
                repo.create_file(path, f"Add {path},  version {uuid_cache}", content or "")
                print(f"Added: {path}")
                cache_doc = cache_doc.reference.get()

                added_success.add(path)
            except GithubException as e:
                if e.status == 422:
                    print(f"Already exists (skipped): {path}")
                    added_success.add(path)
                else:
                    print(f"Error creating {path}: {e}")
                    failed_status(found_in_queue, item, cache_doc)

        # REMOVE CURRENT FILE THAT HAS JUST BEEN PUSHED
            remove_from_cache(cache_doc, uuid_cache)

        
# MODIFIED files: files that are in both old and new paths
        updated_uuids = []
        push_queue = cache_doc.to_dict().get("queue", [])
        queue_items = cache_doc.to_dict().get("queue_item", [])
        modified = old_paths & new_paths

        for path in modified:
            file_info = new_info.get(path, {})
            uuid_cache = file_info.get("uuid_cache", "") #takes uuid_cache from last-modified
            content = None
            found_in_queue = False

            for item in queue_items:
                if isinstance(item, dict) and item.get("uuid_cache") == uuid_cache: #makes sure to find the item in the queue with the same uuid_cache
                    content = item.get("content")
                    found_in_queue = True
                    break

            if found_in_queue:  # it means content was modified and should be pushed

                already_updated_same_path = any(
                    entry["path"] == path and entry["uuid_cache"] != uuid_cache #if for the same path there are more uuids it means there is a conflict
                    for entry in updated_uuids
                )

                if already_updated_same_path:
                    print(f"⏸ File {path} è stato aggiornato di recente. Inserisco in coda.")
                    # Inserisci nella queue e queue_item
                    put_in_queue(uuid_cache, path, content, cache_doc) #put in queue
                    continue

                try:
                    file = repo.get_contents(path)
                    print(f"Pushing: {content}")
                    repo.update_file(file.path, f"Update {path}, version {uuid_cache}", content or "", file.sha)

                    updated_uuids.append({"uuid_cache": uuid_cache, "path": path})
                    print(f"2-File.sha: {file.sha}")
                    print(f" ✅ Push completata: {path} for content {content}")
           
                    # Rimuovi dalla cache una volta pushato
                  

                except GithubException as e:
                    print(f" Errore aggiornando {path}: {e}")

                    # Se errore di tipo 409 (SHA mismatch), metti in coda
                    if e.status == 409:
                        print(f" Conflitto SHA su {path} for {content}, inserisco in coda.")
                        put_in_queue(uuid_cache, path, content, cache_doc)
                       
                    else:
                        failed_status(found_in_queue, item, cache_doc)
                remove_from_cache(cache_doc, uuid_cache)

                # Refresh cache_doc to get the latest state from Firestore
                doc_snapshot = cache_doc.reference.get()
                queue_items = doc_snapshot.to_dict().get("queue_item", [])
                in_queue = list(queue_items)
                print(f"Queue items after removal of in progress: {in_queue}")
                process_queue(repo, doc_snapshot)



        
        # update the last-modified info
        try:
            doc_ref.update({
                "last-modified": data["last-modified"]
            })
        except GoogleCloudError as e:
            print(f"Firestore update failed: {e}")



    def delete_project(self, repo_name):
        repo = self.get_current_repo(repo_name)
        try:
            repo.delete()
            print(f"Repository {repo_name} deleted successfully")
        except GithubException as e:
            print(f"Error deleting {repo}: {e}")



















