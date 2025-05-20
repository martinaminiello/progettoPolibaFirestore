import os

import requests
from firebase_admin import storage
from github import GithubException
import base64
import utils

import time

def retry_with_backoff(func, retries=3, delay=5, backoff=2):
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= backoff
            else:
                raise


class Repository:

    def __init__(self, user):
        self.user = user



    def get_repo_path_from_name(self, name): #builds path from name
        path=self.user.user_dir + '/' + name
        return path

      #it's necessary to use github api here instead of PyGithub since it doesn't encode binary files
    def upload_binary_file(self, bucket_name, file, content_bytes, commit_msg):
        url = f"https://api.github.com/repos/{self.user.username}/{bucket_name}/contents/{file}"

        content_b64 = base64.b64encode(content_bytes).decode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.user.token}",
            "Accept": "application/vnd.github+json"
        }

        data = {
            "message": commit_msg,
            "content": content_b64,
            "branch": "main"
        }

        response = requests.put(url, headers=headers, json=data)

        if response.status_code == 201:
            print(f"File '{file}' created.")
        else:
            print(f"Error: {response.status_code}")
            print(response.text)














    def get_current_repo(self, projectfolder): #gets last repo object of current user
        username = self.user.username
        repo_path=os.path.join(username,projectfolder)
        print(f"getcurrentrepo {repo_path}")
        repo = self.user.github.get_repo(username + '/' + projectfolder)
        print(f"Repo object retrieved from github: {repo}")
        return repo





    def create_new_repo(self, bucket):
        try:
            # create repository on git
            repo = self.user.github.get_user().create_repo(name=bucket)
        except GithubException as e:
            print(f"Status: {e.status}, Error: ", e)
            if e.status == 422:
                print(f"Repository already exists! No need to create another one")
                return

    def create_new_subdirectory(self, object_path, project_folder):
        print(f"Repo: {project_folder}")
        print(f"Object path: {object_path}")
        repo = self.get_current_repo(project_folder)


        file_ext = [".png", ".jpeg", ".jpg", ".pdf"]
        bucket = storage.bucket()  # usa il bucket di default
        blob = bucket.blob(object_path)

        try:
            if "." in object_path:  # è un file
                if any(object_path.lower().endswith(ext) for ext in file_ext):
                    content_bytes = blob.download_as_bytes()
                    retry_with_backoff(lambda: self.upload_binary_file(
                        project_folder, object_path, content_bytes, f"Added image {object_path}"
                    ))
                    print(f"Binary file {object_path} uploaded to GitHub")
                else:
                    content = blob.download_as_text()
                    retry_with_backoff(lambda: repo.create_file(
                        object_path, f"Created {object_path}", content
                    ))
                    print(f"Text file {object_path} created on GitHub")
            else:
                # Creazione di una directory "vuota" = placeholder .gitignore
                retry_with_backoff(lambda: repo.create_file(
                    os.path.join(object_path, ".gitignore"), f"Created folder {object_path}", ""
                ))
                print(f"Folder {object_path} created on GitHub")

        except GithubException as e:
            print("GitHub exception:", e)
        except Exception as e:
            print("Error during upload or download:", e)

    def delete_file(self, file_path,folder_name):
        repo = self.get_current_repo(folder_name)
        contents = repo.get_contents(file_path)
        try:
         repo.delete_file(contents.path, f"removed {file_path}", contents.sha)
        except GithubException as e:
            print("GitHub exception:", e)





