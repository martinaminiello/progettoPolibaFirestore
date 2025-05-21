import os
from pathlib import PurePosixPath
from github import GithubException



class Repository:

    def __init__(self, user):
        self.user = user



    def get_current_repo(self, repo_name):
        username = self.user.username
        repo = self.user.github.get_repo(f"{username}/{repo_name}") # no os.path.join, github needs '/'
        print(f"Repo object retrieved from github: {repo}")
        return repo


    def rename_repo(self, new_name, old_name):
        repo=self.get_current_repo(old_name)
        repo.edit(name=new_name)
        print(f"Repository renominated as: {new_name}")


    def create_new_repo(self, repo_name):
        try:
            # create repository on git
            repo = self.user.github.get_user().create_repo(name=repo_name)
        except GithubException as e:
            print(f"Status: {e.status}, Error: ", e)
            if e.status == 422:
                print(f"Repository already exists! No need to create another one")
                return

    def create_new_subdirectory(self, path, type, repo_name):
        print(f"Repo name: {repo_name}")
        print(f"Object path: {path}")
        print(f"Type: {type}")
        repo = self.get_current_repo(repo_name)

        path_obj = PurePosixPath(path) #manages both \ and /

        if type == "file":
            folder_path = path_obj.parent  #removes file.ext
            created_folder = PurePosixPath()


            for part in folder_path.parts:
                created_folder = created_folder / part
                repo.create_file(
                    str(created_folder / ".gitignore"),
                    f"Created folder at {created_folder}",
                    ""
                )

            try:
                repo.create_file(str(path_obj), f"Created file at {path_obj}", "")
                print(f"File {path_obj} created on GitHub")
            except Exception as e:
                print("Error creating file:", e)

        elif type=="dir":

            created_folder = PurePosixPath()
            try:
                for part in path_obj.parts:
                    created_folder = created_folder / part
                    repo.create_file(
                        str(created_folder / ".gitignore"),
                        f"Created folder at {created_folder}",
                        ""
                    )
                print(f"Folder structure {path_obj} created on GitHub")
            except Exception as e:
                print("Error creating folders:", e)
        else:
            print(f"Type is null: {type}")




    def delete_file(self, type, file_path,repo_name):
        repo = self.get_current_repo(repo_name)
        contents = repo.get_contents(file_path)
        try:
            if type=="file":
             repo.delete_file(file_path, f"removed {file_path}", contents.sha)
            elif type=="dir":
               folder_content=self.list_all_files_in_folder(repo, file_path)
               for file in folder_content:
                   print(f"Deleting {file}")
                   contents=repo.get_contents(file_path)
                   repo.delete_file(file, f"removed {file}", contents.sha)

        except GithubException as e:
            print("GitHub exception:", e)




    def list_all_files_in_folder(self,repo, folder_path):

        all_files = []

        try:
            contents = repo.get_contents(folder_path)
        except Exception as e:
            print(f"Error recovering folder contents {folder_path}: {e}")
            return all_files

        for content in contents:
            if content.type == "file":
                all_files.append(content.path)
            elif content.type == "dir":
                # ricorsion subfolders
                all_files.extend(self.list_all_files_in_folder(repo, content.path))

        return all_files



    def update_file(self, old_path, new_path, repo_name):
        repo = self.get_current_repo(repo_name)

        try:
            contents = repo.get_contents(os.path.join(old_path))
            print(f"Old path{old_path} ")
            print(f"content.sha {contents.sha} deleted")
            repo.delete_file(old_path,f"removed {old_path}", contents.sha)
            print(f"{old_path} deleted")
            repo.create_file(new_path,f"updated {old_path} with new path: {new_path}", "")
        except GithubException as e:
            print("GitHub exception:", e)














