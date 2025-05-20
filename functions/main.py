# The Cloud Functions for Firebase SDK to create Cloud Functions and set up triggers.
import os
from repomanager import Repository
from user import User

from firebase_admin import initialize_app, firestore
from firebase_functions import storage_fn
from dotenv import load_dotenv

from github import Github, Auth


app = initialize_app()

load_dotenv()
token = os.getenv("GITHUB_TOKEN")
if not token:
     raise Exception("Token not found!")
auth = Auth.Token(token)
g = Github(auth=auth)
print(f"User f{g.get_user().login}")
u = User(token)
repository = Repository(u)


@storage_fn.on_object_finalized(bucket="(default)")
def folder_created(event: storage_fn.CloudEvent[storage_fn.StorageObjectData]):
     """it's triggered when a new folder is created in storage or a new file is uploaded"""
     print(" Cloud Function Triggered: folder_created")
     object_data = event.data
     bucket_name=object_data.bucket
     # every bucket=gitrepository
     #if repository with bucket doesn't exist it creates one
     repository.create_new_repo(bucket_name)
     print(f"Bucket: {bucket_name}")
     folder_name = object_data.name
     print(f"{folder_name} was created in {bucket_name}")
     repository.create_new_subdirectory(bucket_name,folder_name)

@storage_fn.on_object_deleted(bucket="(default)")
def folder_deleted(event: storage_fn.CloudEvent[storage_fn.StorageObjectData]):
     """it's triggered when a  folder or file is deleted in storage"""
     print(" Cloud Function Triggered: folder_deleted")
     object_data = event.data
     bucket_name=object_data.bucket
     # every bucket=gitrepository
     #if repository with bucket doesn't exist it creates one
     repository.create_new_repo(bucket_name)
     print(f"Bucket: {bucket_name}")
     folder_name = object_data.name
     print(f"{folder_name} was deleted in {bucket_name}")
     repository.delete_subdirectory(bucket_name,folder_name)
