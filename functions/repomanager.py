import os
import uuid
import datetime
import json
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

    



    def create_tree(self, file_paths, repo_name,last_modified_info, cache_doc):
        print(f"Repo name: {repo_name}")
        repo = self.get_current_repo(repo_name)

 
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
            except Exception as e:
                print(f"Unexpected error: {e}")

                    



    def update_tree(self, repo_name, new_info, cache_doc,doc_ref, added, deleted, modified):
        repo = self.get_current_repo(repo_name)
        print(f"[UPDATE_TREE] add: {added}, delete: {deleted}, modified: {modified}")
        snapshot = doc_ref.get()
        last_mod_items = snapshot.to_dict().get("last-modified", [])
        print(f"QUEUE IN UPDATE_TREE: {last_mod_items}")

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

        def get_queue_snapshot():
            snapshot = cache_doc.reference.get()
            update_time = snapshot.update_time
            queue_items = snapshot.to_dict().get("queue_item", [])
            print(f"[queue] {len(queue_items)} items")
            print(f"QUEUE IN UPDATE_TREE: {queue_items}")
            return snapshot, update_time, queue_items

        # DELETE
        for item in deleted:
            print(f"[delete] {item}")
            if isinstance(item, dict):
                path = item.get("path")
            else:
                path = item  # string
            print(f"[delete] {path}")
            try:
                safe_delete_file(repo, path)
            except GoogleCloudError as e:
                print(f"[error] Deleting {path} failed: {e}")
            except GithubException as e:
                if e.status == 409:
                    try:
                        file = repo.get_contents(path)
                        repo.delete_file(path, f"Delete {path}", file.sha)
                    except GithubException as e2:
                        print(f"[delete] Still failed to delete {path}: {e2}")
                else:
                    raise
            clean_cache(path, cache_doc)

        # ADD
        for item in added:
            if isinstance(item, dict):
                path = item.get("path")
                last_mod_entry = last_mod_items.get(path)
                if last_mod_entry:
                    uuid_cache = last_mod_entry.get("uuid_cache")
                else:
                    uuid_cache = None
                print(f"ADD - uuid_cache: {uuid_cache}")

            file_info = new_info.get(path, {})

            snapshot, update_time, queue_items = get_queue_snapshot()
            queue_item = next((i for i in queue_items if i.get("uuid_cache") == uuid_cache), None)
            content = queue_item.get("content") if queue_item else None

            if not content:
                print(f"[warn] Content not found for {path} (uuid: {uuid_cache}), skipping")
                continue

            try:
                cache_doc.reference.update(
                    {"queue_item": ArrayRemove([queue_item])},
                    firestore.Client.write_option(last_update_time=update_time)
                )
                repo.create_file(path, f"Add {path}, version {uuid_cache}", content)
                print(f"[add] Created {path}")
            except FailedPrecondition:
                print(f"[firestore] Precondition failed for {path}")
            except GithubException as e:
                print(f"[github] Create failed: {e}")
                if queue_item:
                    failed_status(queue_item, cache_doc)
                if e.status == 409:
                    time.sleep(1)
                    try:
                        repo.create_file(path, f"Add {path}, version {uuid_cache}", content)
                        print(f"[add] Retry success: {path}")
                    except GithubException as e2:
                        print(f"[add] Still failed: {e2}")
            clean_cache(path, cache_doc)

        # MODIFY
        print(f"[modify] {modified}")
        for item in modified:
            if isinstance(item, dict):
                path = item.get("path")
            else:
                path = item  # È una stringa

            last_mod_entry = last_mod_items.get(path)
            if last_mod_entry:
                uuid_cache = last_mod_entry.get("uuid_cache")
            else:
                uuid_cache = None
            print(f"MODIFY CONTENT - uuid_cache: {uuid_cache}")
         
            print(f"[modify] {path}")

            for attempt in range(10):
                snapshot, update_time, queue_items = get_queue_snapshot()
                queue_item = next((i for i in queue_items if i.get("uuid_cache") == uuid_cache), None)

                if not queue_item:
                    time.sleep(0.5)
                    continue

                try:
                    file = repo.get_contents(path)
                    repo.update_file(
                        path,
                        f"Update {path}, version {uuid_cache}",
                        queue_item["content"],
                        file.sha
                    )
                    print(f"[modify] Updated {path} to version {uuid_cache}")
                    cache_doc.reference.update(
                        {"queue_item": ArrayRemove([queue_item])},
                        firestore.Client.write_option(last_update_time=update_time)
                    )
                    break
                except GithubException as e:
                    print(f"[github] Modify failed: {e}")
                    if e.status == 409:
                        time.sleep(1)
                        continue
                    failed_status(queue_item, cache_doc)
                    break

            clean_cache(path, cache_doc)











    def delete_project(self, repo_name):
        repo = self.get_current_repo(repo_name)
        try:
            repo.delete()
            print(f"Repository {repo_name} deleted successfully")
        except GithubException as e:
            print(f"Error deleting {repo}: {e}")