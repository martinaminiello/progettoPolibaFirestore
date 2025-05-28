# The Cloud Functions for Firebase SDK to create Cloud Functions and set up triggers.
import firebase_admin
from repomanager import Repository
from user import User
from firebase_admin import initialize_app, firestore, credentials
from firebase_functions import firestore_fn
from github import Github, Auth
import  uuid


if not firebase_admin._apps:
    firebase_admin.initialize_app()

# nothing can be initialized outside the cloud functions, not even tokens, repositories
# everything must be inside the cloud functions or deploy will fail!
# that's the reason you will see repetitive code inside the cloud functions

# With deployed cloud functions is not possible to load the token from an .env file
#TOKEN CANNOT BE SHARED HERE (not even in comments) OR GITHUB WILL INTERCEPT IT AND DEACTIVATE IT!!!


@firestore_fn.on_document_created(document="projects/{docId}")
def project_created(event: firestore_fn.Event) -> None:
    print("On project created triggered")
    db = firestore.client()
    Collection_name = "current_projects"
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
        repo_url=repository.get_repo_url(myuuid)
        doc_id = event.params["docId"]
        db.collection(Collection_name).document(doc_id).update({
            "repo_uuid": myuuid })  #uuid is memorized in firestore
        db.collection(Collection_name).document(doc_id).update({"repo": repo_url})
        tree = object_data.get("tree") #retrieves tree from object event
        if not tree:
            print("No 'tree' found in document.") #user creates project for the first time (so it's empty)
            return

        file_paths = repository.extract_file_paths(tree) #build all files paths from the tree
        for path in file_paths:
            print(f"{path}")
        repository.create_tree(file_paths, tree, myuuid)


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
        Collection_name = "current_projects"
        doc_id = event.params["docId"]
        doc_ref = db.collection(Collection_name).document(doc_id)


        object_data_new = event.data.after.to_dict()
        object_data_old = event.data.before.to_dict()

        old_path = object_data_old.get("tree")
        new_path = object_data_new.get("tree")

        my_uuid = event.data.after.to_dict().get("repo_uuid") #retrieves uuid so it knows which repository must be updated
        if not my_uuid:
            print("repo_uuid not found.")
            return



        if (old_path is None and new_path) or (old_path != new_path): # so if old tree is null () (user creates empty project)
         repository.update_tree(old_path,new_path,my_uuid, doc_ref )        # it still works


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
