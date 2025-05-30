# The Cloud Functions for Firebase SDK to create Cloud Functions and set up triggers.
import firebase_admin
from google.cloud.exceptions import GoogleCloudError
from google.cloud.firestore_v1 import FieldFilter, ArrayUnion
from google.cloud.firestore_v1 import DELETE_FIELD
import utils
from repomanager import Repository
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
    db = firestore.client()
    Collection_name = "projects"
    # remember to also change the path in cloud functions parameter(document="current_projects/{docId}"
    # github authentication
    token = "token"
    auth = Auth.Token(token)
    g = Github(auth=auth)
    print(f"User {g.get_user().login}")
    u = User(token)
    repository = Repository(u)

    doc_id = event.params["docId"]
    doc_ref = db.collection(Collection_name).document(doc_id)
    doc_snapshot = doc_ref.get()
    data = doc_snapshot.to_dict() or {}
    myuuid = data.get("repo_uuid")
    if myuuid:
        print(f"Repository already exists! {myuuid}")
    else:

        myuuid = str(uuid.uuid4())
        object_data = event.data.to_dict()
        repository.create_new_repo(myuuid) #repo name is a unique id
        repo_url=repository.get_repo_url(myuuid) #build repo url

        doc_id = event.params["docId"]
        db.collection(Collection_name).document(doc_id).update({
            "repo_uuid": myuuid })  #uuid is stored in firestore

        db.collection(Collection_name).document(doc_id).update({"repo": repo_url})# repo_url is stored in firestore

        timestamp = datetime.datetime.now(datetime.timezone.utc)
        db.collection(Collection_name).document(doc_id).update({
            "creation-time": timestamp #creation date is stored in firestore
        })

        tree = object_data.get("tree") #retrieves tree from object event
        last_modified_info = object_data.get("last-modified") #retrieves last modified info from object event
        if not tree:
            print("No 'tree' found in document.") #user creates project for the first time (so it's empty)
            return

        file_paths = repository.extract_file_paths(tree) #build all files paths from the tree
        repository.create_tree(file_paths, myuuid, last_modified_info)
        if last_modified_info:
            updates = {}
            for file_path in last_modified_info:
                updates[f"last-modified.{file_path}.content"] = DELETE_FIELD
                updates[f"last-modified.{file_path}.uuid_cache"] = DELETE_FIELD
            try:
             db.collection(Collection_name).document(doc_id).update(updates)
            except GoogleCloudError as e:
                print(f"Firestore content deletion failed: {e}")



@firestore_fn.on_document_updated(document="projects/{docId}")
def project_updated(event: firestore_fn.Event) -> None:
        print("On project updated triggered")

        # github authentication
        token = "token"
        auth = Auth.Token(token)
        g = Github(auth=auth)
        print(f"User f{g.get_user().login}")
        u = User(token)
        repository = Repository(u)

        db = firestore.client()
        Collection_name = "projects"
        doc_id = event.params["docId"]
        doc_ref = db.collection(Collection_name).document(doc_id)


        object_data_new = event.data.after.to_dict()
        object_data_old = event.data.before.to_dict()

        old_path = object_data_old.get("tree")
        new_path = object_data_new.get("tree")
        last_modified_info = object_data_new.get("last-modified")

        my_uuid = event.data.after.to_dict().get("repo_uuid") #retrieves uuid so it knows which repository must be updated
        if not my_uuid:
            print("repo_uuid not found.")
            return

        if (old_path is None and new_path) or (old_path != new_path): # so if old tree is null () (user creates empty project)
         repository.update_tree(old_path,new_path,my_uuid, doc_ref, last_modified_info )        # it still works
        if last_modified_info:
            updates = {}
            for file_path in last_modified_info:
                updates[f"last-modified.{file_path}.content"] = DELETE_FIELD
                updates[f"last-modified.{file_path}.uuid_cache"] = DELETE_FIELD
            try:
             db.collection(Collection_name).document(doc_id).update(updates)
            except GoogleCloudError as e:
                print(f"Firestore content deletion failed: {e}")

@firestore_fn.on_document_deleted(document="projects/{docId}")
def project_deleted(event: firestore_fn.Event) -> None:

        print("On project deleted triggered")
        # github authentication
        token = "token"
        auth = Auth.Token(token)
        g = Github(auth=auth)
        print(f"User f{g.get_user().login}")
        u = User(token)
        repository = Repository(u)
        my_uuid = event.data.to_dict().get("repo_uuid")
        repository.delete_project(my_uuid)



########################################## REALTIME DATABASE FUNCTIONS #################################################

@db_fn.on_value_created(reference="/active_projects/{projectId}")
def oncreate(event: db_fn.Event) -> None:
    raw_data = event.data # rtdb gives already a dictionary
    print(f"Realtime database on create: {raw_data}")
    data = utils.convert_tree_keys(raw_data)
    print(f"Sanitized data: {data}")
    tree=data.get("tree")
    print(f"Tree: {tree}")
    db = firestore.client()
    project_id = data['id']
    Collection_name = "projects"
    users_id = data['current-authors']
    # Ensure users_id is a list of user IDs
    if isinstance(users_id, dict):
        users_id = list(users_id.values())
    elif not isinstance(users_id, list):
        users_id = [users_id]

    doc_ref = db.collection(Collection_name).document(project_id)
    doc_snapshot = doc_ref.get()
    
    

    tree_firestore, last_modified_info = utils.split_tree(tree)
    data["tree"] = tree_firestore  # realtime tree is converted to firestore tree
    last_modified = utils.insert_last_modified(last_modified_info)  # calcola last_modified prima di usarlo
    data["last-modified"] = last_modified["last-modified"]  # aggiungi last-modified direttamente a data

    if doc_snapshot.exists:  # if the project document already exists, it will not be created again
        print(f"Document with ID {project_id} already exists!")
    else:
        try:
            db.collection(Collection_name).document(project_id).set(data)  # creates new document with project data
        except GoogleCloudError as e:
            print(f"Firestore creation failed: {e}")

    if not isinstance(users_id, list):
        users_id = [users_id]

    user_docs = list( # retrieves all users that are current-authors of the project
        db.collection("users")
        .where(filter=FieldFilter("id", "in", users_id))
        .stream()
    )
    user_project = {
        'id': project_id,
        'workbench': False,
        'active': True,
        'tags': "" # tags will be retrieved from the client app
    }


    user_id=""
    if not user_docs:
        print(f"User {user_id} doesn't exist.")
    else:
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


@db_fn.on_value_updated(reference="/active_projects/{projectId}")
def onupdate(event: db_fn.Event) -> None:
    print("Realtime database on update triggered")
    db = firestore.client()
    Collection_name = "projects"
    project_id = event.params["projectId"]
    token = "token"
    auth = Auth.Token(token)
    g = Github(auth=auth)
    print(f"User {g.get_user().login}")
    u = User(token)
    repository = Repository(u)
    doc_ref = db.collection(Collection_name).document(project_id)
    repo_name=doc_ref.get("repo_uuid")

    before = event.data.before
    after = event.data.after


    
    doc_snapshot = doc_ref.get()
    if not doc_snapshot.exists:
        print(f"Document {project_id} does not exist in Firestore.")
        return

    updates = {}

    # update simple fields
    for field in ["title", "current-authors", "owners"]:
        if before.get(field) != after.get(field):
            updates[field] = after.get(field)


    old_tree = event.data.before.get("tree", {})
    new_tree = event.data.after.get("tree", {})
    old_last_modified=doc_ref.get("last-modified", {})
    #update tree only for added or removed files
    if before.get("tree") != after.get("tree"):
        repository.update_tree(old_tree, new_tree, repo_name, doc_ref, old_last_modified)

    




