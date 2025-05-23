import os
from github import GithubException



class Repository:

    def __init__(self, user):
        self.user = user



    def get_current_repo(self, repo_name):
        username = self.user.username
        repo = self.user.github.get_repo(f"{username}/{repo_name}") # no os.path.join, github needs '/'
        print(f"Repo object retrieved from github: {repo}")
        return repo



    def create_new_repo(self, repo_name):
        try:
            # create repository on git
            self.user.github.get_user().create_repo(name=repo_name)
        except GithubException as e:
            print(f"Status: {e.status}, Error: ", e)
            if e.status == 422:
                print(f"Repository already exists! No need to create another one")
                return


    def extract_file_paths(self,tree_map, current_path=""):
        paths = []

        if not isinstance(tree_map, dict):
            print("Tree map is not a dictionary.")
            return paths

        for key, value in tree_map.items():
            new_path = f"{current_path}/{key}" if current_path else key
            # builds path like this "current_path/key" if current path is not empty, otherwise just "key"
            if isinstance(value, dict):
                #if value is a another map (another folder) does recursion
                paths.extend(self.extract_file_paths(value, new_path))
            elif isinstance(value, str): #if values is a string (just a file) adds it to paths
                 paths.append(new_path)
        return paths


    def get_file_content(self,tree_map, file_path):
        keys = file_path.split('/')
        current = tree_map
        for key in keys:
            if isinstance(current, dict) and key in current: #if key is in the tree
                current = current[key] #retrieves content, for example current[main.tex]=content
            else:
                return None
        return current if isinstance(current, str) else None

    def create_tree(self, file_paths, tree, repo_name):
        print(f"Repo name: {repo_name}")
        repo = self.get_current_repo(repo_name)

        for path in file_paths:
            content = self.get_file_content(tree, path)

            if content is not None:
                try:
                    repo.create_file(path, f"Add file {path}", content)
                    print(f"File created at {path}")
                except GithubException as e:
                    if e.status == 422:
                        print(f"File already exists: {path}")
                    else:
                        print(f"Error creating new file: {path}: {e}")

    def update_tree(self, old_tree, new_tree, repo_name):
        repo = self.get_current_repo(repo_name)

        #I turn paths in sets, so I can use set operations (union, difference..)
        old_paths = set(self.extract_file_paths(old_tree))
        new_paths = set(self.extract_file_paths(new_tree))

        # deleted file: files that are no longer in new paths
        deleted = old_paths - new_paths
        for path in deleted:
            try:
                file = repo.get_contents(path)
                repo.delete_file(file.path, f"Remove {path}", file.sha)
                print(f"Deleted: {path}")
            except GithubException as e:
                print(f"Error deleting {path}: {e}")

        # added files: files that aren't in old paths
        added = new_paths - old_paths
        for path in added:
            content = self.get_file_content(new_tree, path) or ""
            try:
                repo.create_file(path, f"Add {path}", content)
                print(f"Added: {path}")
            except GithubException as e:
                if e.status == 422:
                    print(f"Already exists (skipped): {path}")
                else:
                    print(f"Error creating {path}: {e}")

        # content modified: I only check files in both to be sure
        common = old_paths & new_paths
        for path in common:
            old_content = self.get_file_content(old_tree, path) or ""
            new_content = self.get_file_content(new_tree, path) or ""
            if old_content != new_content:
                try:
                    contents = repo.get_contents(path)
                    repo.update_file(
                        contents.path,
                        f"Updated content of {path}",
                        new_content,
                        contents.sha
                    )
                    print(f"Updated: {path}")
                except GithubException as e:
                    print(f"Error updating {path}: {e}")

    def delete_project(self, repo_name):
        repo=self.get_current_repo(repo_name)

        try:
            repo.delete()
            print(f"Repository {repo_name} deleted successfully")
        except GithubException as e:
            print(f"Error deleting {repo}: {e}")















