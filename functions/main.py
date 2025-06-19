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
    file_paths = repository.extract_file_paths_with_names(tree)
    print(f"[project_created] file_paths: {file_paths} ")
  
    cache_doc= utils.create_cache_doc(db)
    if not cache_doc:
        print("No cache found.")
        return
    try:
            repository.create_tree(file_paths, myuuid, last_modified_info, cache_doc)
    except Exception as e:
            print(f"Errore in create_tree: {e}")





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

    old_tree = event.data.before.to_dict().get("tree", {})
    print(f"Old tree: {old_tree}")
    new_tree = event.data.after.to_dict().get("tree", {})
    print(f"New tree: {new_tree}")

    new_info=event.data.after.to_dict().get("last-modified", {})
    print(f"New info: {new_info}")
    old_info=event.data.before.to_dict().get("last-modified", {})
    print(f"Old info: {old_info}")
    

    old_paths = set(repository.extract_paths(old_tree))
    new_paths = set(repository.extract_paths(new_tree))

 

    trees_different = old_tree != new_tree
  

    print(f"Trees different? {trees_different}")
    

    cache_doc = utils.create_cache_doc(db)
    snapshot = cache_doc.reference.get()
    queue_items = snapshot.to_dict().get("queue_item", [])
    print(f"on project updated queue: {queue_items}")

    
    modified_content_paths = []

    # Intersezione tra old e new paths: quelli che esistono sia su GitHub sia nel nuovo tree
    intersecting_paths = old_paths.intersection(new_paths)
    print(f"inetrsecting paths  {intersecting_paths}")

    for path in intersecting_paths:
        try:
            print(f"Retrievieng content from  {path}")

            file_content = repo.get_contents(path)
            content_str = file_content.decoded_content.decode('utf-8')
            print(f"content retrieved : {content_str}")
        except GithubException as e:
            print(f"Error retrieving content from GitHub for {path}: {e}")
            continue

        # uuid_cache si prende dal NEW info, perché è lo stato più aggiornato
        uuid_cache = new_info.get(path, {}).get("uuid_cache")
        print(f"UUID new from path {path}: {uuid_cache}")
        if not uuid_cache:
            print(f"No uuid_cache found for {path} in new_info.")
            continue

        # Confronta con ogni item in coda
        for item in queue_items:
            if item.get("uuid_cache") == uuid_cache:
                if item.get("content") != content_str:
                    modified_content_paths.append(path)
                break



    print(f"modified content: {modified_content_paths}")
    if cache_doc:
        cache_dict = cache_doc.to_dict().get
    else:
        print("No cache document found.")

  
    if trees_different  or modified_content_paths:
        repository.update_tree(old_tree, new_tree, repo_name, doc_ref, old_info, new_info, cache_doc, modified_content_paths)
    else:
        print("No changes detected in tree or last-modified, update skipped.")
        
    


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


    #Firestore db is initialized 
    db = firestore.client()
    project_id = data['id']
    Collection_name = "projects"
    doc_ref = db.collection(Collection_name).document(project_id)
    doc_snapshot = doc_ref.get()


    
    if doc_snapshot.exists:  # if the project document already exists, it will not be created again
        print(f"Document with ID {project_id} already exists!")
        return
    else:
        try:
            ###FIRESTORE DOCUMENT CREATION WITH TREE ELABORATION###
            tree_real_time=data.get("tree")
            print(f"realtime  tree: {tree_real_time}")

            cache_doc= utils.create_cache_doc(db)
            tree_firestore, last_modified_info = utils.split_tree_with_name(tree_real_time)

            readable_file_info, reverse_map = utils.convert_file_info_keys_to_readable(last_modified_info, tree_firestore)

            last_modified = utils.insert_last_modified(readable_file_info, timestamp)
            data["last-modified"] = last_modified["last-modified"]

            for readable_path, file_info in last_modified['last-modified'].items():
                uuid_cache = file_info.get("uuid_cache")
                
                internal_path = reverse_map.get(readable_path)
                if internal_path is None:
                    print(f"[WARN] No internal path found for {readable_path}")
                    continue

                content = last_modified_info.get(internal_path, {}).get("content")
                if content is None:
                    print(f"[WARN] Content not found for internal path {internal_path}")
                    continue

                print(f"uuid {uuid_cache}, content {content}")
                repomanager.update_cache_in_progress(cache_doc, uuid_cache, content, readable_path, timestamp)

            data["tree"] = tree_firestore  # realtime tree is converted to firestore tree
            data["last-edit"] = timestamp

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

    # updates simple fields
    for field in ["title", "current-authors", "owners", "co-authors"]:
        if before.get(field) != after.get(field):
            updates[field] = after.get(field)

    def update_user_projects(user_id: str, project_id: str, active_value: bool):
        user_ref = db.collection("users").document(user_id)
        user_doc = user_ref.get()
        if not user_doc.exists:
            print(f"User {user_id} does not exist.")
            return
        projects = user_doc.get("projects") or []
        updated_projects = []
        found = False
        for proj in projects:
            if proj.get("id") == project_id:
                proj = dict(proj)
                proj['active'] = active_value
                found = True
            updated_projects.append(proj)
        if not found:
            updated_projects.append({
                'id': project_id,
                'workbench': False,
                'active': active_value,
                'tags': ""
            })
        user_ref.update({"projects": updated_projects})
        print(f"Updated project {project_id} active={active_value} for user {user_id}.")

    try:
        if updates:
            doc_ref.update(updates)
            print(f"Updated simple fields: {updates}")

        #  current-authors
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

            not_current_anymore = before_authors - after_authors
            just_added = after_authors - before_authors

            for user_id in not_current_anymore:
                update_user_projects(user_id, project_id, False)

            for user_id in just_added:
                update_user_projects(user_id, project_id, True)

        # co-authors
        if "co-authors" in updates:
            co_authors_id = after["co-authors"]
            if isinstance(co_authors_id, dict):
                co_authors_id = list(co_authors_id.values())
            elif not isinstance(co_authors_id, list):
                co_authors_id = [co_authors_id]

            before_coauthors = before.get("co-authors", [])
            if isinstance(before_coauthors, dict):
                before_coauthors = list(before_coauthors.values())
            elif not isinstance(before_coauthors, list):
                before_coauthors = [before_coauthors]

            removed_coauthors = set(before_coauthors) - set(co_authors_id)
            added_coauthors = set(co_authors_id) - set(before_coauthors)

            # removes project from removed co-authors 
            for removed_id in removed_coauthors:
                user_ref = db.collection("users").document(removed_id)
                user_doc = user_ref.get()
                if user_doc.exists:
                    projects = user_doc.get("projects") or []
                    updated_projects = [proj for proj in projects if proj.get('id') != project_id]
                    user_ref.update({"projects": updated_projects})
                    print(f"Removed project {project_id} from {removed_id}.")

            # aadd project to new co-authors with active=False
            for added_id in added_coauthors:
                update_user_projects(added_id, project_id, False)

    except GoogleCloudError as e:
        print(f"Error updating simple fields: {e}")


    
    doc_snapshot = doc_ref.get()
    #update tree  for added or removed files and for modified content

    cache_doc= utils.create_cache_doc(db)

    if cache_doc:
        cache_dict = cache_doc.to_dict()
    else:
        print("No cache document found.")
        
    print(f" before tree: {before.get("tree")}, after tree: {after.get("tree")}")
    if before.get("tree") != after.get("tree"):
       
        try:
            repository.update_firestore(event, repo_name, doc_ref, cache_doc, time)
        
        except Exception as e:
            print(f"Error in update_firestore: {e}")



@db_fn.on_value_deleted(reference="/active_projects/{projectId}")
def ondelete(event: db_fn.Event) -> None:
    print("Realtime database on delete triggered")

 
    db = firestore.client()
    Collection_name = "projects"
    project_id = event.params["projectId"]
    doc_ref = db.collection(Collection_name).document(project_id)
    doc_snapshot = doc_ref.get()
    time = event.time
    print(f"TIME : {time}")

    deleted_data = event.data  # information befere deletion

    if not doc_snapshot.exists:
        print(f"Document {project_id} does not exist in Firestore.")
        return

    try:
        before_authors = deleted_data.get("current-authors", [])
        
        if isinstance(before_authors, dict):
            before_authors = set(before_authors.values())
        else:
            before_authors = set(before_authors)

        for inactive in before_authors:
            user_ref = db.collection("users").document(inactive)
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

        doc_ref.update({
            "current-authors": firestore.ArrayRemove(list(before_authors))
        })

    except Exception as e:
        print(f"Error in updating active field at real-time deletion: {e}")







