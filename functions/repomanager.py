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














    def get_current_repo(self, bucket_name): #gets last repo object of current user
        username = self.user.username
        repo = self.user.github.get_repo(username + '/' + bucket_name)
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

    def create_new_subdirectory(self, bucket_name, object_name):
        repo = self.get_current_repo(bucket_name)
        print(f"create_new_subdir, repo: {repo}")
        print(f"create_new_subdir, directory_name: {object_name}")

        file_ext = [".png", ".jpeg", ".jpg", ".pdf"]
        bucket = storage.bucket(bucket_name)
        blob = bucket.blob(object_name)

        try:
            if "." in object_name:  # it's a file
                if any(object_name.lower().endswith(ext) for ext in file_ext):
                    content_bytes = blob.download_as_bytes()

                    retry_with_backoff(lambda: self.upload_binary_file(
                        bucket_name, object_name, content_bytes, f"added image {object_name}"
                    ))
                    print(f"Binary file {object_name} uploaded to GitHub")


                else:
                    content = blob.download_as_text()
                    retry_with_backoff(lambda: repo.create_file(
                        object_name, f"created {object_name}", content
                    ))
                    print(f"Text file {object_name} created on GitHub")

            else:
                # Create a placeholder .gitignore in the folder
                retry_with_backoff(lambda: repo.create_file(
                    os.path.join(object_name, ".gitignore"), f"created {object_name}", ""
                ))
                print(f"Folder {object_name} created on GitHub")

        except GithubException as e:
            print("GitHub exception:", e)
        except Exception as e:
            print("Error during upload or download:", e)


 #   def delete_subdirectory(self, bucket_name,folder_name):
  #      repo = self.get_current_repo(bucket_name)
  #      utils.push(self.get_last_repo_path(), "Removed dir " + folder_name)





