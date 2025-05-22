# The Cloud Functions for Firebase SDK to create Cloud Functions and set up triggers.
import os
import firebase_admin
from repomanager import Repository
from user import User
from firebase_admin import initialize_app, firestore, credentials
from firebase_functions import storage_fn, firestore_fn
from dotenv import load_dotenv
from github import Github, Auth
import populate_firestore
cred = credentials.Certificate("credentialsfirestore.json")
firebase_admin.initialize_app(cred)

#guthub authentication
load_dotenv()
token = os.getenv("GITHUB_TOKEN")
if not token:
     raise Exception("Token not found!")
auth = Auth.Token(token)
g = Github(auth=auth)
print(f"User f{g.get_user().login}")
u = User(token)
repository = Repository(u)
db = firestore.client()



@firestore_fn.on_document_created(document="documents/{docId}")
def project_created(event: firestore_fn.Event) -> None:
    print("On project created triggered")
    object_data = event.data.to_dict()
    title=object_data.get("title")
    repository.create_new_repo(title)
    tree = object_data.get("tree")
    if not tree:
        print("No 'tree' found in document.")
        return

    file_paths = repository.extract_file_paths(tree)
    for path in file_paths:
        print(f" {path}")
    repository.create_tree(file_paths, tree, title)

@firestore_fn.on_document_updated(document="documents/{docId}")
def project_updated(event: firestore_fn.Event) -> None:
        print("On project renominated triggered")
        object_data = event.data
        old_data = object_data.before.to_dict()
        new_data = object_data.after.to_dict()

        old_title = old_data.get("title")
        title = new_data.get("title")
        if new_data != old_title:
            repository.rename_repo(title, old_title)

        object_data_new = event.data.after.to_dict()
        object_data_old = event.data.before.to_dict()
        old_path = object_data_old.get("tree")
        new_path = object_data_new.get("tree")
        if old_path != new_path:
            repository.update_tree(old_path, new_path, title)




