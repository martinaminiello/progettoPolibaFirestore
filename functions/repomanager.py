import os
import uuid
import datetime
from github import GithubException
from google.cloud.exceptions import GoogleCloudError
from google.cloud.firestore_v1 import DELETE_FIELD
import utils


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


    def update_firestore(self, old_tree, new_tree, repo_name, doc_ref, old_info, new_info):
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
                    "content": content,
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
                
                # update the Firestore document with the new tree and last-modified info
                doc_ref.update({
                    "tree": data["tree"],
                    "last-modified": data["last-modified"]
                })
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
                            "content": content,
                            "last-modifier": last_modifier,
                            "uuid_cache": uuid_cache,
                            "timestamp": timestamp
                        }
                        
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




    def update_tree(self, old_tree, new_tree, repo_name, doc_ref, old_info, new_info):
        repo = self.get_current_repo(repo_name)
        print(f" update_tree: {repo_name} - old_tree: {old_tree}, new_tree: {new_tree}, doc_ref: {doc_ref}, old_info: {old_info}, new_info: {new_info}")
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
            content = file_info.get("content", "")
            last_modifier = file_info.get("last-modifier", "")
            if not content and not last_modifier:
                file_info = new_modified_dict.get(path, {})
                content = file_info.get("content", "")
                last_modifier = file_info.get("last-modifier", "")
            uuid_cache = str(uuid.uuid4())
            print(f"Adding file at {path} with content: {repr(content)} and last modifier: {last_modifier}")


            
            try:
                repo.create_file(path, f"Add {path},  version {uuid_cache}", content or "")
                print(f"Added: {path}")
                added_success.add(path)
            except GithubException as e:
                if e.status == 422:
                    print(f"Already exists (skipped): {path}")
                    added_success.add(path)
                else:
                    print(f"Error creating {path}: {e}")

        # for each added file, remove content and uuid_cache from last-modified
        for file_path in added_success:
            if file_path in data["last-modified"]:
                if "content" in data["last-modified"][file_path]:
                    del data["last-modified"][file_path]["content"]
                if "uuid_cache" in data["last-modified"][file_path]:
                    del data["last-modified"][file_path]["uuid_cache"]
        
        # MODIFIED files: files that are in both old and new paths
        modified = old_paths & new_paths
        for path in modified:
            if new_info.get(path, {}).get("content") != old_info.get(path, {}).get("content"):
                print(f"Modifying file at {path}")
                file_info = new_info.get(path, {})
                content = file_info.get("content", "")
                last_modifier = file_info.get("last-modifier", "")
                uuid_cache = str(uuid.uuid4())
                try:
                    file = repo.get_contents(path)
                    repo.update_file(file.path, f"Update {path}, version {uuid_cache}", content or "", file.sha)
                    print
                    print(f"finito: {path}")
                except GithubException as e:
                    print(f"Error updating {path}: {e}")
                # after updating, remove content and uuid_cache from last-modified
                if path in data["last-modified"]:
                    if "content" in data["last-modified"][path]:
                        del data["last-modified"][path]["content"]
                    if "uuid_cache" in data["last-modified"][path]:
                        del data["last-modified"][path]["uuid_cache"]
        
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



















