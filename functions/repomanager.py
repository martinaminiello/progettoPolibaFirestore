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


    def update_firestore(self, old_tree, new_tree, repo_name, doc_ref, old_info, new_info, cache_doc,timestamp):
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
            
                print(f"Adding file at {path} with content: {repr(content)} and last modifier: {last_modifier}")
                # Update the tree structure (not on firestore yet)
                set_nested_dict(data["tree"], path, "")
                # Update the last-modified info (not on firestore yet)
                data["last-modified"][path] = {
                    "last-modifier": last_modifier,
                    "uuid_cache": uuid_cache,
                    "timestamp": timestamp
                }
                
                
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
                    print(f"Modifying file at {path} because content has changed {repr(new_info.get(path, {}).get('content'))}")
                    file_info = new_info.get(path, {})
                    content = file_info.get("content", "")
                    last_modifier = file_info.get("last-modifier", "")
                    uuid_cache = str(uuid.uuid4())
                 
                    
                    print(f"Modified: {path}")
                    # Update the last-modified info
                    data["last-modified"][path] = {
                            "last-modifier": last_modifier,
                            "uuid_cache": uuid_cache,
                            "timestamp": timestamp
                        }
                    
                    update_cache_in_progress(cache_doc, uuid_cache, content, path, timestamp)
                        
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
                    failed_status(item, cache_doc)


        

        # MODIFIED files: files that are in both old and new paths
        cache_doc = cache_doc.reference.get()
        queue_items = cache_doc.to_dict().get("queue_item", [])
        modified = old_paths & new_paths

        for path in modified:
            path_items = [item for item in queue_items if item.get("path") == path]
            if not path_items:
                continue
            last_item = max(path_items, key=lambda x: x.get("timestamp", 0))
            old_items = [item for item in path_items if item != last_item]
            print(f"last_item: {last_item}")
            updated_items = []
            failed_items = []
            content = last_item.get("content")
            max_retries = 3
            success = False
            for attempt in range(max_retries):
                try:
                    file = repo.get_contents(path)
                    print(f"Pushing: {content} (attempt {attempt+1})")
                    repo.update_file(
                        file.path,
                        f"Update {path}, version {last_item.get('uuid_cache')}",
                        content or "",
                        file.sha
                    )
                    print(f" ✅ Push completed: {path} for content {content}")
                    success_item = dict(last_item)
                    success_item["push_status"] = "success"
                    updated_items.append(success_item)
                    for old in old_items:
                        failed_item = dict(old)
                        failed_item["push_status"] = "failed"
                        updated_items.append(failed_item)
                    success = True
                    break
                except GithubException as e:
                    print(f" Error pushing {path}: {e}")
                    if e.status == 409 and attempt < max_retries - 1:
                        print("SHA conflict, retrying after delay...")
                        time.sleep(2)  
                        continue  
                    elif e.status == 409:
                        try:
                            file = repo.get_contents(path)
                            repo.update_file(
                                file.path,
                                f"Force update {path}, version {last_item.get('uuid_cache')}",
                                content or "",
                                file.sha
                            )
                            print(f" ✅ Forced push completed: {path} for content {content}")
                            success_item = dict(last_item)
                            success_item["push_status"] = "success"
                            updated_items.append(success_item)
                            for old in old_items:
                                failed_item = dict(old)
                                failed_item["push_status"] = "failed"
                                failed_items.append(failed_item)
                            success = True
                            break
                        except Exception as e2:
                            print(f"Error forcing remote content after SHA conflict: {e2}")
                            failed_item = dict(last_item)
                            failed_item["push_status"] = "failed"
                            updated_items.append(failed_item)
                            for old in old_items:
                                failed_item = dict(old)
                                failed_item["push_status"] = "failed"
                                failed_items.append(failed_item)
                            break
                    else:
                        failed_item = dict(last_item)
                        failed_item["push_status"] = "failed"
                        updated_items.append(failed_item)
                        for old in old_items:
                            failed_item = dict(old)
                            failed_item["push_status"] = "failed"
                            failed_items.append(failed_item)
                        break

            cache_doc = cache_doc.reference.get()
            queue_items = cache_doc.to_dict().get("queue_item", [])
            to_remove = [item for item in queue_items if isinstance(item, dict) and item.get("path") == path]
            print(f"Removing all items from queue with path {path}: {to_remove}")
            if to_remove:
                cache_doc.reference.update({"queue_item": ArrayRemove(to_remove)})

            print(f"Pushed items: {updated_items}")
            print(f"Failed, cancelled commits: {failed_items}")

            
        

    
       





    def delete_project(self, repo_name):
        repo = self.get_current_repo(repo_name)
        try:
            repo.delete()
            print(f"Repository {repo_name} deleted successfully")
        except GithubException as e:
            print(f"Error deleting {repo}: {e}")



















