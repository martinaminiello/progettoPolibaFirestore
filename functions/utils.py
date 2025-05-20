import os
import subprocess




def push(repo_path, commit_message):

    try:
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
        subprocess.run(["git", "commit", "-m", commit_message], cwd=repo_path, check=True)
        subprocess.run(["git", "push"], cwd=repo_path, check=True)
        print("All changes have been saved!")
    except subprocess.CalledProcessError as e:
        print("Error: ", e)
        print("Make sure you saved your changes on your local disk before you commit.")
