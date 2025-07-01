# The Cloud Functions for Firebase SDK to create Cloud Functions and set up triggers.
import firebase_admin
from google.cloud.exceptions import GoogleCloudError
from google.cloud.firestore_v1 import FieldFilter, ArrayUnion
from google.cloud.firestore_v1 import DELETE_FIELD
import utils
from github import GithubException
from repomanager import Repository
import repomanager
import time
import os
from user import User
from firebase_admin import initialize_app, firestore, credentials
from firebase_functions import firestore_fn
from github import Github, Auth
from firebase_functions import db_fn
import  uuid

import datetime
if not firebase_admin._apps:
    firebase_admin.initialize_app()

# nothing can be initialized outside the cloud functions, not even tokens, repositories...
# everything must be inside the cloud functions or deploy will fail!
# that's the reason you will see repetitive code inside the cloud functions

# With deployed cloud functions is not possible to load the token from an .env file
#TOKENS CANNOT BE SHARED HERE (not even in comments) OR GITHUB WILL INTERCEPT THEM AND DEACTIVATE THEM!!!


########################################### FIRESTORE FUNCTIONS ########################################################

@firestore_fn.on_document_created(document="projects/{docId}")
def project_created(event: firestore_fn.Event) -> None:
    print("On project created triggered")
    
    repository=utils.initialized_repo()

    db = firestore.client()
    Collection_name = "projects"
    doc_id = event.params["docId"]
    
    myuuid = str(uuid.uuid4())
    object_data = event.data.to_dict()

    try: #repo creation
      repository.create_new_repo(myuuid) #repo name is a unique id
    except GithubException as e:
        print(f"Status: {e.status}, Error: ", e)
        if e.status == 422:
            print(f"Repository already exists!")
            return 
        
    
    #uuid is stored in firestore
    repo_url=repository.get_repo_url(myuuid) #build repo url
    db.collection(Collection_name).document(doc_id).update({
            "repo_uuid": myuuid })  
    # repo_url is stored in firestore
    db.collection(Collection_name).document(doc_id).update({"repo": repo_url})
    #creation time is generated and stored in firestore
    timestamp = datetime.datetime.now(datetime.timezone.utc)
    db.collection(Collection_name).document(doc_id).update({
            "creation-time": timestamp 
        })

   
   
    #retrieves last modified info from object event
    last_modified_info = object_data.get("last-modified") 


    doc_ref = db.collection(Collection_name).document(doc_id)
    doc_data = doc_ref.get().to_dict() 
    last_modified = doc_data.get("last-modified")

    paths=utils.extract_paths_from_last_modified(last_modified)
    uuid_map=utils.assign_uuids(paths)
    tree=utils.build_tree_with_uuids(paths, uuid_map)
    db.collection(Collection_name).document(doc_id).update({
            "tree": tree 
        })

    print("on create tree: ", tree)
    cache_doc= utils.create_cache_doc(db)
    if not cache_doc:
        print("No cache found.")
        return
    try:
            repository.create_tree(paths, myuuid, last_modified_info, cache_doc)
    except Exception as e:
            print(f"Error in create_tree: {e}")




@firestore_fn.on_document_updated(document="projects/{docId}")
def project_updated(event: firestore_fn.Event) -> None:
    print("On project updated triggered")

    repository=utils.initialized_repo()

    db = firestore.client()
    Collection_name = "projects"
    project_id = event.params["docId"]
    doc_ref = db.collection(Collection_name).document(project_id)
    doc_snapshot = doc_ref.get()
    repo_name = doc_snapshot.get("repo_uuid")
    repo=repository.get_current_repo(repo_name)

    tree = event.data.before.to_dict().get("tree", {})
    print(f"Old tree: {tree}")
    new_tree = event.data.after.to_dict().get("tree", {})
    print(f"New tree: {new_tree}")

    new_info=event.data.after.to_dict().get("last-modified", {})
    print(f"New info: {new_info}")
    old_info=event.data.before.to_dict().get("last-modified", {})
    print(f"Old info: {old_info}")
    

    paths_from_last_mod=utils.extract_paths_from_last_modified(new_info)
    print(f"Extract paths from last modified: {paths_from_last_mod}")
 

    last_modified_different=old_info!= new_info
    print(f"Last modified different? {last_modified_different}")
    

    cache_doc = utils.create_cache_doc(db)
    snapshot = cache_doc.reference.get()
    queue_items = snapshot.to_dict().get("queue_item", [])
    print(f"on project updated queue: {queue_items}")

    
    uuid_map_tree = utils.generate_uuid_path_map_from_tree(tree)
    print(f"on project updated uuid map Tree: {uuid_map_tree}")
    

    paths_mod_set = set(paths_from_last_mod)  
    cache_list = [item for item in queue_items if item.get("path") in paths_mod_set]
         
    new_uuid_map_last_mod=utils.generate_uuid_path_map_from_cache(cache_list)
    print(f"on project updated uuid map Last Modified: {new_uuid_map_last_mod}")
    print(f"ITEMS IN CACHE: {cache_list}")

    #DELETED PATHS
    deleted_items = [item for item in queue_items if item.get("to_delete")== True]
    deleted_paths = [item["path"] for item in deleted_items]
         

    #RENOMINATED PATHS
    renominated_items = []
    paths_before_renominated = []

    for uuid_id, path_old in uuid_map_tree.items():
        path_new = new_uuid_map_last_mod.get(uuid_id)
        if path_new:
            if os.path.basename(path_old) != os.path.basename(path_new):
                renominated_items.append(path_new)
                paths_before_renominated.append(path_old)
    print("RENOMINATED paths:", renominated_items)
    print("BEFORE RENOMINATED paths:", paths_before_renominated)
    
    #MOVED PATHS
    moved_items = []
    paths_before_moved = []

    for uuid_id, path_old in uuid_map_tree.items():
        path_new = new_uuid_map_last_mod.get(uuid_id)
        if path_new:  #excludes renominated paths
            if path_old != path_new and os.path.basename(path_old) == os.path.basename(path_new):
                moved_items.append(path_new)
                paths_before_moved.append(path_old)
    print("MOved paths:", moved_items)
    print("BEFORE MOVED paths:", paths_before_moved)
   

    
    #MODIFIED PATHS IN CONTENT 
    modified_content_items = [item for item in cache_list if item.get("modified") is True]
    modified_paths = [item["path"] for item in modified_content_items]

    print(f"Modified content paths: {modified_paths}")

    #ADDED PATHS
    added_items = [
    item for item in cache_list
    if not item.get("uuid") or item["uuid"] not in uuid_map_tree 
]
    #generating new uuids
    for item in added_items:
        if not item.get("uuid"):
            item["uuid"] = str(uuid.uuid4())

    added_paths = [item["path"] for item in added_items]
    print("Added paths:", added_paths)

    

    # Build all added items
    renominated_adds = [{"uuid": uuid_id, "path": path} for uuid_id, path in new_uuid_map_last_mod.items() if path in renominated_items]
    moved_adds = [{"uuid": uuid_id, "path": path} for uuid_id, path in new_uuid_map_last_mod.items() if path in moved_items]
    final_added_items = added_items + renominated_adds + moved_adds

    # Update the tree
    updated_tree = utils.update_firestore_tree(tree, final_added_items, deleted_paths)
    print(f"tree: {updated_tree}")

    if last_modified_different:
        # Update Firestore only if last-modified changes (last-modified changes trigger tree buildiing)
        doc_ref.update({"tree": updated_tree})
    else:
        print("No changes to tree, skipping Firestore update.")

    print(f"PATHS TO ADD: ", final_added_items)
    print(f"PATHS TO DELETE: ", deleted_paths)
    
    if  last_modified_different:
            print("Entering if to update tree")
            repository.update_tree(repo_name, new_info, cache_doc, doc_ref, final_added_items, deleted_paths, modified_paths)
    else:
        print("No changes detected in tree or in the queue.")
   
 
    


@firestore_fn.on_document_deleted(document="projects/{docId}")
def project_deleted(event: firestore_fn.Event) -> None:
    print("On project deleted  triggered")

    repository=utils.initialized_repo()

    my_uuid = event.data.to_dict().get("repo_uuid")
    repository.delete_project(my_uuid)
    data = event.data.to_dict() if hasattr(event.data, 'to_dict') else event.data
    db = firestore.client()
    project_id = data['id']
    print(f"Project {project_id} deleted from Firestore.")
   









