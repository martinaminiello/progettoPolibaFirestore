import os
import uuid
import datetime
from github import GithubException
from google.cloud.exceptions import GoogleCloudError
from google.cloud.firestore_v1 import DELETE_FIELD
import utils


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
            # Sostituisci l'ultimo '_' con '.' solo se non c'è già un punto
            if isinstance(value, dict) and "content" in value and "last-modifier" in value:
                # Considera che il file può essere in una sottocartella
                new_key = key
                if "_" in key and "." not in key:
                    new_key = key[::-1].replace("_", ".", 1)[::-1]  # solo l'ultimo _
                new_path = f"{current_path}/{new_key}" if current_path else new_key
                paths.append(new_path)
            else:
                new_path = f"{current_path}/{key}" if current_path else key
                if isinstance(value, dict):
                    paths.extend(self.extract_file_paths(value, new_path))
                elif isinstance(value, str):
                    # Anche qui, se è un file semplice
                    new_key = key
                    if "_" in key and "." not in key:
                        new_key = key[::-1].replace("_", ".", 1)[::-1]
                    new_path = f"{current_path}/{new_key}" if current_path else new_key
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




    def update_tree(self, old_tree, new_tree, repo_name, doc_ref, old_last_modified_info):
        repo = self.get_current_repo(repo_name)

        old_paths = set(self.extract_file_paths(old_tree))
        new_paths = set(self.extract_file_paths(new_tree))

        # Usa split_tree per ottenere info file dal nuovo tree
        new_tree_structure, file_info_dict = utils.split_tree(new_tree)
        new_modified_dict = utils.insert_last_modified(file_info_dict)["last-modified"]

        # deleted file: files that are no longer in new paths
        deleted = old_paths - new_paths
        print("old_paths:", old_paths)
        print("new_paths:", new_paths)
        for path in deleted:
            print("To delete: ", path)
            try:
                file = repo.get_contents(path)
                repo.delete_file(file.path, f"Remove {path}", file.sha)
                #devo usare il dizionario 
                #TO DO
                doc_ref.update({f"tree.{path}": DELETE_FIELD})
                doc_ref.update({f"last-modified.{path}": DELETE_FIELD})
                print(f"Deleted: {path}")
            except GithubException as e:
                print(f"Error deleting {path}: {e}")
            except GoogleCloudError as e:
                print(f"Unexpected error in Firestore deleting {path}: {e}")

        # added files: files that aren't in old paths
        added = new_paths - old_paths
        print("old_paths:", old_paths)
        print("new_paths:", new_paths)
        for path in added:
            print("To add: ", path)
            # Recupera info dal dizionario dei metadati
            file_info = new_modified_dict.get(path, {})
            content = file_info.get("content", "")
            last_modifier = file_info.get("last-modifier", "")
            uuid_cache = str(uuid.uuid4())
            timestamp = datetime.datetime.now(datetime.timezone.utc)
            print(f"Adding file at {path} with content: {repr(content)} and last modifier: {last_modifier}")

            # Aggiorna Firestore (normalizza solo per Firestore)
            firestore_path = path.replace("/", "-").replace(".", "_")
            doc_ref.update({f"tree.{firestore_path}": ""})
            doc_ref.update({f"last-modified.{firestore_path}": {
                "content": content,
                "last-modifier": last_modifier,
                "uuid_cache": uuid_cache,
                "timestamp": timestamp
            }})

   
            try:
                repo.create_file(path, f"Add {path}, version {uuid_cache}", content or "")
                print(f"Added: {path}")
            except GithubException as e:
                if e.status == 422:
                    print(f"Already exists (skipped): {path}")
                else:
                    print(f"Error creating {path}: {e}")
 

       

    def delete_project(self, repo_name):
        repo = self.get_current_repo(repo_name)
        try:
            repo.delete()
            print(f"Repository {repo_name} deleted successfully")
        except GithubException as e:
            print(f"Error deleting {repo}: {e}")



















