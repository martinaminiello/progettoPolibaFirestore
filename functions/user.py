
import os

import subprocess


from github import Github, Auth


class User:
    def __init__(self, token):
        self.token = token
        self.auth = Auth.Token(token)
        self.github = Github(auth=self.auth)
        self.user = self.github.get_user()
        self.username = self.user.login
        self.user_url = f"https://github.com/{self.username}/"
        self.user_dir = f"{self.username}_workspace"

        os.makedirs(self.user_dir, exist_ok=True)

