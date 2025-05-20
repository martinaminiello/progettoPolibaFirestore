# The Cloud Functions for Firebase SDK to create Cloud Functions and set up triggers.
import os

from google.cloud import storage

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



#we should know which latex project the user decides to open
bucket="cloudfunctionspoliba.firebasestorage.app"

@storage_fn.on_object_finalized(bucket=bucket)
def folder_created(event: storage_fn.CloudEvent[storage_fn.StorageObjectData]):
     """it's triggered when a new folder is created in storage or a new file is uploaded"""
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
     """it's triggered when a  folder or file is deleted in storage"""
     print(" Cloud Function Triggered: folder_deleted")
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
