# The Cloud Functions for Firebase SDK to create Cloud Functions and set up triggers.
import json
import os
from datetime import datetime
import firebase_admin
from google.cloud import storage
from repomanager import Repository
from user import User
from firebase_admin import initialize_app, firestore, credentials
from firebase_functions import storage_fn, firestore_fn
from dotenv import load_dotenv
from github import Github, Auth

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

#repo_name
doc_ref = db.collection("documents").document("001")
doc = doc_ref.get()
title=""
if doc.exists:
    title = doc.to_dict().get("title")
    title=title.replace(" ", "-")
    print(f"Title from parent doc: {title}")
else:
    raise Exception("Title not found")


@firestore_fn.on_document_updated(document="documents/{docId}")
def project_created(event: firestore_fn.Event) -> None:
    print("On project renominated triggered")
    object_data = event.data.to_dict()
    old_title=object_data.before.get("title")
    title=object_data.after.get("title")
    repository.rename_repo(title, old_title)

@firestore_fn.on_document_updated(document="documents/{docId}")
def project_updated(event: firestore_fn.Event) -> None:
    print("On project created triggered")
    repository.create_new_repo(title)

@firestore_fn.on_document_created(document="documents/{docId}/001/{subDocId}")
def document_created(event: firestore_fn.Event) -> None:
    print("On document created triggered")
    object_data = event.data.to_dict()
    path=object_data.get("name")
    print(f"Name: {path}")
    type=object_data.get("type")
    print(f"Type: {type}")
    repository.create_new_subdirectory(path, type, title)

@firestore_fn.on_document_updated(document="documents/{docId}/001/{subDocId}")
def document_updated(event: firestore_fn.Event)-> None:
    print("On document updated triggered")
    object_data_new = event.data.after.to_dict()
    object_data_old= event.data.before.to_dict()
    print(object_data_new)
    old_path=object_data_old.get("name")
    new_path=object_data_new.get("name")
    print(f"old: {old_path}, new: {new_path}")
    repository.update_file(old_path,new_path,title)

@firestore_fn.on_document_deleted(document="documents/{docId}/001/{subDocId}")
def document_deleted(event: firestore_fn.Event)-> None:
    print("On document deleted triggered")

    if event.data:
        object_data = event.data.to_dict()
        type=object_data.get("type")
        print(f"Deleted: {object_data}")
        repository.delete_file( object_data, type,title)
    else:
        print("Deleted document data not available (event.data is None)")









"""
bucket="cloudfunctionspoliba.firebasestorage.app"

@storage_fn.on_object_finalized(bucket=bucket)
def folder_created(event: storage_fn.CloudEvent[storage_fn.StorageObjectData]):
    
     print(" Cloud Function Triggered: folder_created")
     object_data = event.data
     bucket_name=object_data.bucket
     full_path = object_data.name  # "project001/subfolder/file.txt"
     folder_path = full_path.split('/')[0] #project001
     # every project=gitrepository
     #every project has a folder with subfolders and files in the buckets
     #each folder is named 'project00n', with n starting form 1
     #if repository with bucket doesn't exist it creates one

     repository.create_new_repo(folder_path)
     print(f"Bucket: {bucket_name}")

     print(f"{folder_path} was created in {bucket_name}")
     repository.create_new_subdirectory(full_path,folder_path)

@storage_fn.on_object_deleted(bucket=bucket)
def folder_deleted(event: storage_fn.CloudEvent[storage_fn.StorageObjectData]):
  
     object_data = event.data
     bucket_name=object_data.bucket
     full_path = object_data.name  # "project001/subfolder/file.txt"
     folder_path = full_path.split('/')[0]  # project001
     # every bucket=gitrepository
     #if repository with bucket doesn't exist it creates one
     repository.create_new_repo(bucket_name)
     print(f"Bucket: {bucket_name}")

     print(f"{full_path} was deleted in {bucket_name}")
     #foldername to delete
     repository.delete_file(full_path, folder_path)
     print(f"{full_path} deleted successfully.")
     
     
"""

