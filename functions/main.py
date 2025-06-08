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
#TOKENS CANNOT BE SHARED HERE (not even in comments) OR GITHUB WILL INTERCEPT AND DEACTIVATE THEM!!!


########################################### FIRESTORE FUNCTIONS ########################################################

@firestore_fn.on_document_created(document="projects/{docId}")
def project_created(event: firestore_fn.Event) -> None:
    print("On project created triggered")
    
    repository=utils.initialized_repo()

    db = firestore.client()
    Collection_name = "projects"
    doc_id = event.params["docId"]
    doc_ref = db.collection(Collection_name).document(doc_id)
    doc_snapshot = doc_ref.get()
    data = doc_snapshot.to_dict() or {}
   

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

    #retrieves tree from object event
    tree = object_data.get("tree") 
    if not tree:
        #this can happen when user creates project for the first time (so it's still empty)
        print("No 'tree' found in document.") 
        return
    #retrieves last modified info from object event
    last_modified_info = object_data.get("last-modified") 
  
    #build all files paths from the tree
    file_paths = repository.extract_file_paths(tree)
    # delete content and uuid_cache from last_modified_info only if create_tree is successful
    create_tree_success = True
    cache_doc= utils.create_cache_doc(db)
    if not cache_doc:
        print("Nessun documento cache trovato! Impossibile procedere.")
        return
    try:
            repository.create_tree(file_paths, myuuid, last_modified_info, cache_doc)
    except Exception as e:
            print(f"Errore in create_tree: {e}")
            create_tree_success = False

    if last_modified_info and create_tree_success:
            doc = db.collection(Collection_name).document(doc_id).get()
            data = doc.to_dict() or {}
            if "last-modified" in data and isinstance(data["last-modified"], dict):
                for file_path in last_modified_info:
                    if file_path in data["last-modified"]:
                        if "content" in data["last-modified"][file_path]:
                            del data["last-modified"][file_path]["content"]
                     
                try:
                    db.collection(Collection_name).document(doc_id).update({
                        "last-modified": data["last-modified"]
                    })
                    db.collection(Collection_name).document(doc_id).update({
                        "last-edit": data["last-modified"][file_path]["timestamp"]
                    })
                except GoogleCloudError as e:
                    print(f"Firestore content deletion failed: {e}")


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

    old_tree = event.data.before.to_dict().get("tree", {})
    print(f"Old tree: {old_tree}")
    new_tree = event.data.after.to_dict().get("tree", {})
    print(f"New tree: {new_tree}")

    new_info=event.data.after.to_dict().get("last-modified", {})
    print(f"New info: {new_info}")
    old_info=event.data.before.to_dict().get("last-modified", {})
    print(f"Old info: {old_info}")
    
 
    cache_doc= utils.create_cache_doc(db)

    if cache_doc:
        cache_dict = cache_doc.to_dict().get
    else:
        print("No cache document found.")

    
    repository.update_tree(old_tree, new_tree, repo_name, doc_ref,old_info, new_info, cache_doc) 
    
    


@firestore_fn.on_document_deleted(document="projects/{docId}")
def project_deleted(event: firestore_fn.Event) -> None:
    print("On project deleted triggered")

    repository=utils.initialized_repo()

    my_uuid = event.data.to_dict().get("repo_uuid")
    repository.delete_project(my_uuid)
    data = event.data.to_dict() if hasattr(event.data, 'to_dict') else event.data
    db = firestore.client()
    project_id = data['id']
    print(f"Project {project_id} deleted from Firestore.")
    users_id = data.get('co-authors', [])
    print(f"Users to update: {users_id}")
    if isinstance(users_id, dict):
        users_id = list(users_id.values())
    elif not isinstance(users_id, list):
        users_id = [users_id]
    #finds co-authors ids of the delelted project in users collection 
    #and deleted the project for the "projects" field in each user document
    user_docs = db.collection("users").where("id", "in", users_id).stream()
    for user_doc in user_docs:
        user_ref = user_doc.reference
        user_data = user_doc.to_dict() or {}
        projects = user_data.get("projects", [])
        updated_projects = [proj for proj in projects if proj.get('id') != project_id]
        print(f"Updating user {user_data.get('id')} projects: {updated_projects}")
        user_ref.update({"projects": updated_projects})




########################################## REALTIME DATABASE FUNCTIONS #################################################

@db_fn.on_value_created(reference="/active_projects/{projectId}")
def oncreate(event: db_fn.Event) -> None:
    data = event.data # rtdb gives already a dictionary
    print(f"Data: {data}")
    timestamp=event.time


    ###FIRESTORE DOCUMENT CREATION WITH TREE ELABORATION###

    tree_real_time=data.get("tree")
    tree= utils.convert_tree_keys(tree_real_time)  # replaces "_" with "." in tree
    print(f"Sanitized tree: {tree}")
   
    #Firestore db is initialized 
    db = firestore.client()
    project_id = data['id']
    Collection_name = "projects"
    doc_ref = db.collection(Collection_name).document(project_id)
    doc_snapshot = doc_ref.get()

    cache_doc= utils.create_cache_doc(db)


    
    tree_firestore, last_modified_info = utils.split_tree(tree)
    print("tree_structure:", tree_firestore)
    last_modified = utils.insert_last_modified(last_modified_info, timestamp)  # set last-modified
    data["last-modified"] = last_modified["last-modified"] 
    print(f"Last mod info : {last_modified_info}")
    
    for file_path, file_info in last_modified['last-modified'].items():
        uuid_cache = file_info.get("uuid_cache")
        content = last_modified_info.get(file_path, {}).get("content")
    
        path = file_path
        print(f"uuid {uuid_cache}, content {content}")
        repomanager.update_cache_in_progress(cache_doc, uuid_cache, content, path, timestamp)

    data["tree"] = tree_firestore  # realtime tree is converted to firestore tree
    data["last-edit"] = timestamp

    
    if doc_snapshot.exists:  # if the project document already exists, it will not be created again
        print(f"Document with ID {project_id} already exists!")
        return
    else:
        try:
           doc_ref.set(data)  # creates new document with project data
        except GoogleCloudError as e:
            print(f"Firestore creation failed: {e}")


    ###PROJECT CREATION IN USERS###

    users_id = data['co-authors']
    current_authors = data.get('current-authors', [])
    # Ensure users_id and current_authors are lists
    if isinstance(users_id, dict):
        users_id = list(users_id.values())
    elif not isinstance(users_id, list):
        users_id = [users_id]
    if isinstance(current_authors, dict):
        current_authors = list(current_authors.values())
    elif not isinstance(current_authors, list):
        current_authors = [current_authors]

    # union of users_id and current_authors
    all_user_ids = set(users_id) | set(current_authors)
    # list users documents with the same id of all_user_ids
    user_docs = list(
        db.collection("users")
        .where(filter=FieldFilter("id", "in", list(all_user_ids)))
        .stream()
    )
    for user_doc in user_docs:
        user_id = user_doc.get("id")
        is_current = user_id in current_authors
        user_project = {
            'id': project_id,
            'workbench': False,
            'active': is_current,
            'tags': ""
        }
        user_ref = user_doc.reference
        try:
            user_ref.update({
                "projects": ArrayUnion([user_project])
            })
            print(f"Added project {project_id} to {user_id} with active={is_current}.")
        except Exception as e:
            print(f"Error: {user_id}: {e}")





@db_fn.on_value_updated(reference="/active_projects/{projectId}")
def onupdate(event: db_fn.Event) -> None:
    print("Realtime database on update triggered")

    repository=utils.initialized_repo()

    db = firestore.client()
    Collection_name = "projects"
    project_id = event.params["projectId"]
    doc_ref = db.collection(Collection_name).document(project_id)
    doc_snapshot = doc_ref.get()
    repo_name = doc_snapshot.get("repo_uuid")
    time=event.time
    print(f"TIME : {time}")
    before = event.data.before
    after = event.data.after

    #checks if document exists in Firestore
    if not doc_snapshot.exists:
        print(f"Document {project_id} does not exist in Firestore.")
        return

    updates = {}

    # update simple fields
    for field in ["title", "current-authors", "owners", "co-authors"]: #perhaps co-authors is managed directly between the client and Firestore
        if before.get(field) != after.get(field):
            updates[field] = after.get(field)
    if updates:
        try:
            doc_ref.update(updates)
            print(f"Updated simple fields: {updates}")
            
            # update "active" field in users documents
            if "current-authors" in updates:
                before_authors = before.get("current-authors", [])
                after_authors = after.get("current-authors", [])
                if isinstance(before_authors, dict):
                    before_authors = set(before_authors.values())
                else:
                    before_authors = set(before_authors)
                if isinstance(after_authors, dict):
                    after_authors = set(after_authors.values())
                else:
                    after_authors = set(after_authors)
                # users that have no longer the project as active
                not_current_anymore = before_authors - after_authors
                # users for which the project is now active
                just_added = after_authors - before_authors

                if not_current_anymore: #"active": False
                    for deleted in not_current_anymore:
                        user_ref = db.collection("users").document(deleted)
                        user_doc = user_ref.get()
                        if user_doc.exists:
                            projects = user_doc.get("projects") or []
                            updated_projects = []
                            for proj in projects:
                                if proj.get('id') == project_id:
                                    proj = dict(proj)
                                    proj['active'] = False
                                updated_projects.append(proj)
                            user_ref.update({"projects": updated_projects})

                if just_added: #"active": True
                    for added in just_added:
                        user_ref = db.collection("users").document(added)
                        user_doc = user_ref.get()
                        if user_doc.exists:
                            projects = user_doc.get("projects") or []
                            found = False
                            updated_projects = []
                            for proj in projects:
                                if proj.get('id') == project_id:
                                    proj = dict(proj)
                                    proj['active'] = True
                                    found = True
                                updated_projects.append(proj)
                            if not found: # if for some reason project was not created in user profile, it is now
                                updated_projects.append({
                                    'id': project_id,
                                    'workbench': False,
                                    'active': True,
                                    'tags': ""
                                })
                            user_ref.update({"projects": updated_projects})
      
      
            if "co-authors" in updates: 
                co_authors_id = after["co-authors"]
                if isinstance(co_authors_id, dict):
                    co_authors_id = list(co_authors_id.values())
                elif not isinstance(co_authors_id, list):
                    co_authors_id = [co_authors_id]

                # find removed co-authors
                before_coauthors = before.get("co-authors", [])
                if isinstance(before_coauthors, dict):
                    before_coauthors = list(before_coauthors.values())
                elif not isinstance(before_coauthors, list):
                    before_coauthors = [before_coauthors]
                removed_coauthors = set(before_coauthors) - set(co_authors_id)
                # remove project from removed co-authors
                for removed_id in removed_coauthors:
                    user_ref = db.collection("users").document(removed_id)
                    user_doc = user_ref.get()
                    if user_doc.exists:
                        projects = user_doc.get("projects") or []
                        updated_projects = [proj for proj in projects if proj.get('id') != project_id]
                        user_ref.update({"projects": updated_projects})
                        print(f"Removed project {project_id} from {removed_id}.")

                # add project to new co-authors
                user_docs = list(
                    db.collection("users")
                    .where(filter=FieldFilter("id", "in", co_authors_id)) #streams users that are in co-authors
                    .stream()
                )
                user_project = {
                    'id': project_id,
                    'workbench': False,
                    'active': False,
                    'tags': ""
                }
                for user_doc in user_docs:
                    user_id = user_doc.get("id")
                    user_ref = user_doc.reference
                    try:
                        user_ref.update({
                            "projects": ArrayUnion([user_project])
                        })
                        print(f"Added project {project_id} to {user_id}.")
                    except Exception as e:
                        print(f"Error: {user_id}: {e}")
        except GoogleCloudError as e:
            print(f"Error updating simple fields: {e}")

    old_tree_realtime = event.data.before.get("tree", {})
    old_tree_structure=utils.split_tree(old_tree_realtime)[0] #split tree to get the structure
    old_tree=utils.convert_tree_keys(old_tree_structure)
    print(f"onupdate Old tree: {old_tree}")
    
    new_tree_realtime = event.data.after.get("tree", {})
    new_tree_structure=utils.split_tree(new_tree_realtime)[0] #split tree to get the structure
    new_tree=utils.convert_tree_keys(new_tree_structure)
    print(f"onupdate New tree: {new_tree}")

    old_file_info = utils.split_tree(old_tree_realtime)[1]
    old_file_info_converted = utils.convert_tree_keys(old_file_info) #convert old file info keys to be compatible with firestore
    print(f"onupdate Old file info: {old_file_info_converted}")
    
    new_file_info = utils.split_tree(new_tree_realtime)[1]
    new_file_info_converted = utils.convert_tree_keys(new_file_info) #convert new file info keys to be compatible with firestore
    print(f"onupdate New file info: {new_file_info_converted}")
    
    doc_snapshot = doc_ref.get()
    #update tree  for added or removed files and for modified content

    cache_doc= utils.create_cache_doc(db)

    if cache_doc:
        cache_dict = cache_doc.to_dict()
    else:
        print("No cache document found.")
        

    if before.get("tree") != after.get("tree"):
       
        try:
            repository.update_firestore(old_tree, new_tree, repo_name, doc_ref, old_file_info_converted, new_file_info_converted, cache_doc, time)
        
        except Exception as e:
            print(f"Errore in update_tree: {e}")








